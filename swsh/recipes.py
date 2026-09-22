"""Guided composites: one command for a job that is a dozen API calls.

"Set me up a PBX with five extensions" is roughly fifteen requests across SIP
endpoints, addresses and a dial plan. Typing fifteen commands is not the job, and
neither is asking someone to write and maintain a YAML file for a sentence. So a
recipe is a small, ordered list of registry operations with two properties that
make it safe to hand to anyone:

* **It can be previewed.** ``--dry-run`` resolves the whole plan and prints it
  without touching the project. Nothing is created until the plan reads right.
* **It converges.** Each step can declare ``ensure_by``, a field to match an
  existing row on. Re-running a recipe finds what already exists and skips it, so
  a half-finished run is fixed by running it again rather than by unwinding it by
  hand.

The engine is deliberately not a state reconciler. It never deletes, never
diffs against a desired-state file, and never claims to own a resource. It is a
scripted sequence with lookups, which is what a person actually asked for.

Parameters reuse ``resources.Field``, so a recipe gets the same pickers, the same
choice lists and the same non-interactive strictness as any other command, for
free.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import resources as res


@dataclass(frozen=True, slots=True)
class Step:
    """One registry operation inside a recipe."""

    label: str  # shown in the plan, so write it for a human
    resource: str  # registry key
    op: str = "create"
    # Built from the accumulated context: the recipe's parameters plus whatever
    # earlier steps captured. Returning None skips the step entirely, which is
    # how a step becomes conditional on an answer.
    body: Callable[[dict[str, Any]], dict[str, Any] | None] = lambda ctx: {}
    # Field to match an existing row on before creating. This is what makes a
    # re-run converge instead of duplicating. None means always create.
    ensure_by: str | None = "name"
    # Context key to store the resulting row under, so later steps can reference
    # the id of something this step made.
    capture: str | None = None
    # Path parameters for a sub-resource route, e.g. {"fabric_subscriber_id": ...}.
    params: Callable[[dict[str, Any]], dict[str, Any]] = lambda ctx: {}


@dataclass(frozen=True, slots=True)
class Recipe:
    """A named composite, parameterised like any other command."""

    key: str
    title: str
    help: str = ""
    params: tuple[res.Field, ...] = field(default_factory=tuple)
    steps: Callable[[dict[str, Any]], list[Step]] = lambda ctx: []

    @property
    def fields(self) -> tuple[res.Field, ...]:
        """Alias so a Recipe duck-types as a Resource.

        `cli._parse_pairs` and `prompts.fill_missing` both read `.fields` /
        `.form_fields()`. Exposing the parameters under those names is what lets a
        recipe reuse the whole typed-value and picker path instead of growing its
        own argument handling.
        """
        return self.params

    def form_fields(self, mode: str = "create") -> list[res.Field]:
        return list(self.params)


@dataclass(frozen=True, slots=True)
class PlannedStep:
    """A step with its body resolved, ready to show or run."""

    step: Step
    body: dict[str, Any]
    params: dict[str, Any]
    method: str
    path: str


@dataclass(slots=True)
class StepResult:
    label: str
    action: str  # "created" | "reused" | "skipped" | "failed"
    detail: str = ""
    row: dict[str, Any] | None = None


def coerce_params(recipe: Recipe, values: dict[str, Any]) -> dict[str, Any]:
    """Turn raw parameter strings into the types the recipe declared.

    Reuses the registry's coercion so `--extensions 5` becomes an int and a
    comma-separated list becomes a list, with the same error messages.
    """
    out: dict[str, Any] = {}
    problems: list[str] = []
    missing: list[str] = []
    for f in recipe.params:
        if f.name not in values or values[f.name] is None:
            if f.required:
                missing.append(f.title)
            continue
        try:
            coerced = res.coerce(f, values[f.name])
        except ValueError as exc:
            problems.append(str(exc))
            continue
        if coerced is None:
            if f.required:
                missing.append(f.title)
            continue
        out[f.name] = coerced
    if problems:
        raise ValueError("; ".join(problems))
    if missing:
        raise ValueError(f"required: {', '.join(missing)}")
    return out


def plan(recipe: Recipe, ctx: dict[str, Any]) -> list[PlannedStep]:
    """Resolve every step's body and route without issuing anything.

    Steps that capture an id from an earlier step cannot know it yet, so the
    plan shows the placeholder the runner will fill. That is honest: a dry-run
    reports the shape of the work, not a simulation of its results.
    """
    from . import spec

    planned: list[PlannedStep] = []
    for step in recipe.steps(ctx):
        body = step.body(ctx)
        if body is None:
            continue
        target = res.BY_KEY.get(step.resource)
        method, path = "?", f"<unknown resource {step.resource}>"
        if target is not None:
            operation_id = target.rest_ops.get(step.op)
            if operation_id is None:
                operation_id = next(
                    (e.spec_op for e in target.extras
                     if e.method == step.op and e.spec_op), step.op
                )
            op_def = spec.get(operation_id, api=target.api) if target.api else None
            if op_def is not None:
                method, path = op_def.method, op_def.path
            else:
                method, path = "?", f"<no spec operation for {step.resource}.{step.op}>"
        planned.append(
            PlannedStep(step=step, body=body, params=step.params(ctx),
                        method=method, path=path)
        )
    return planned


async def _find_existing(client, target: res.Resource, field_name: str,
                         value: Any, params: dict[str, Any]) -> dict[str, Any] | None:
    """Look for a row whose ``field_name`` already equals ``value``."""
    if "list" not in target.rest_ops and not target.can_list:
        return None
    try:
        payload = await client.invoke(target, "list", **params)
    except Exception:
        # A recipe must not fail because a convergence check could not run; the
        # create below will surface any real problem with a real error.
        return None
    for row in res.unwrap(payload, target.data_key):
        if str(row.get(field_name, "")) == str(value):
            return row
    return None


async def run(recipe: Recipe, ctx: dict[str, Any], client) -> list[StepResult]:
    """Execute a recipe, reusing anything that already matches.

    Stops at the first genuine failure rather than pressing on, because a later
    step almost always depends on an earlier one, and a cascade of errors buries
    the one that mattered.
    """
    results: list[StepResult] = []
    context = dict(ctx)

    for step in recipe.steps(context):
        body = step.body(context)
        if body is None:
            results.append(StepResult(step.label, "skipped"))
            continue
        target = res.BY_KEY.get(step.resource)
        if target is None:
            results.append(StepResult(step.label, "failed",
                                      f"unknown resource '{step.resource}'"))
            break
        params = step.params(context)

        if step.ensure_by and step.ensure_by in body:
            existing = await _find_existing(
                client, target, step.ensure_by, body[step.ensure_by], params
            )
            if existing is not None:
                if step.capture:
                    context[step.capture] = existing
                results.append(StepResult(
                    step.label, "reused",
                    str(existing.get(target.id_field, "")), existing
                ))
                continue

        try:
            row = await client.invoke(target, step.op, body=body, **params)
        except Exception as exc:
            results.append(StepResult(step.label, "failed", str(exc)))
            break
        if step.capture:
            context[step.capture] = row
        results.append(StepResult(
            step.label, "created", str((row or {}).get(target.id_field, "")), row
        ))

    return results


# --------------------------------------------------------------------- recipes


def _pbx_steps(ctx: dict[str, Any]) -> list[Step]:
    """Extensions, each dialable, plus a SWML script as the dial plan.

    Platform-level dial plans are not available yet: pattern matching on inbound
    and outbound, captures, and contexts-as-resources are all specified but
    unimplemented. SWML is the supported way to route between extensions today,
    which is why the dial plan here is a script rather than a context.

    UNVERIFIED. The composition below has not been run against a live space. The
    field names come from the registry, but whether an extension needs a
    subscriber as well as a SIP endpoint, and what the script must contain to
    reach one, both need confirming with `scripts/verify_registry.py` and a
    scratch project before this is trustworthy.
    """
    prefix = int(ctx.get("start_extension", 1001))
    count = int(ctx.get("extensions", 5))
    name = ctx["name"]

    steps: list[Step] = []
    for i in range(count):
        ext = prefix + i
        steps.append(Step(
            label=f"extension {ext}",
            resource="sip",
            op="create",
            ensure_by="name",
            capture=f"ext_{ext}",
            body=lambda ctx, ext=ext, name=name: {
                "name": f"{name}-{ext}",
                "username": str(ext),
                "caller_id": str(ext),
            },
        ))
    steps.append(Step(
        label="dial plan (SWML script)",
        resource="swml",
        op="create",
        ensure_by="name",
        capture="dialplan",
        body=lambda ctx, name=name, prefix=prefix, count=count: {
            "name": f"{name}-dialplan",
            "contents": {
                "sections": {
                    "main": [
                        {"answer": {}},
                        {"connect": {"to": "%{call.to_extension}"}},
                    ]
                }
            },
        },
    ))
    return steps


PBX = Recipe(
    key="pbx",
    title="PBX",
    help="PREVIEW, unverified. N SIP extensions plus a SWML dial plan.",
    params=(
        res.Field("name", required=True, help="Prefix for everything this creates."),
        res.Field("extensions", kind="int", required=True,
                  help="How many extensions to create."),
        res.Field("start_extension", kind="int",
                  help="First extension number. Default 1001."),
    ),
    steps=_pbx_steps,
)


RECIPES: tuple[Recipe, ...] = (PBX,)
BY_KEY: dict[str, Recipe] = {r.key: r for r in RECIPES}


def get(key: str) -> Recipe | None:
    """Exact key, then unique prefix, matching how resources resolve."""
    key = key.strip()
    if key in BY_KEY:
        return BY_KEY[key]
    hits = [r for r in RECIPES if r.key.startswith(key)]
    return hits[0] if len(hits) == 1 else None
