"""The recipe engine: guided composites over registry operations.

Two properties carry the whole design, and both are tested here rather than
trusted: a recipe can be previewed without touching a project, and re-running it
converges instead of duplicating.
"""

from __future__ import annotations

from typing import Any

import pytest

from swsh import recipes
from swsh import resources as res


class FakeClient:
    """Records invocations and can pretend rows already exist."""

    def __init__(self, existing: dict[str, list[dict]] | None = None,
                 error: Exception | None = None):
        self.existing = existing or {}
        self.error = error
        self.calls: list[tuple[str, str, dict]] = []
        self._n = 0

    async def invoke(self, resource: Any, op: str, *, body: dict | None = None,
                     **params: Any) -> Any:
        self.calls.append((resource.key, op, dict(body or {})))
        if op == "list":
            return {"data": self.existing.get(resource.key, [])}
        if self.error is not None:
            raise self.error
        self._n += 1
        return {"id": f"{resource.key}-{self._n}", **(body or {})}

    def writes(self) -> list[tuple[str, str]]:
        return [(k, op) for k, op, _ in self.calls if op != "list"]


SIMPLE = recipes.Recipe(
    key="simple", title="Simple", help="one queue",
    params=(res.Field("name", required=True),
            res.Field("size", kind="int")),
    steps=lambda ctx: [
        recipes.Step(label="a queue", resource="queues", ensure_by="name",
                     capture="q",
                     body=lambda c: {"name": c["name"], "max_size": c.get("size", 10)}),
        recipes.Step(label="conditional", resource="queues", ensure_by=None,
                     body=lambda c: {"name": "second"} if c.get("size") else None),
    ],
)


class TestParameters:
    def test_values_are_coerced_to_declared_types(self):
        ctx = recipes.coerce_params(SIMPLE, {"name": "support", "size": "25"})
        assert ctx == {"name": "support", "size": 25}

    def test_a_missing_required_parameter_is_an_error(self):
        with pytest.raises(ValueError, match="required: name"):
            recipes.coerce_params(SIMPLE, {"size": "3"})

    def test_a_bad_int_names_the_field(self):
        with pytest.raises(ValueError, match="size"):
            recipes.coerce_params(SIMPLE, {"name": "x", "size": "not-a-number"})

    def test_a_recipe_duck_types_as_a_resource(self):
        # cli._parse_pairs and prompts.fill_missing both read these.
        assert SIMPLE.fields == SIMPLE.params
        assert [f.name for f in SIMPLE.form_fields("create")] == ["name", "size"]


class TestPlan:
    def test_plan_resolves_the_real_method_and_path(self):
        planned = recipes.plan(SIMPLE, {"name": "support", "size": 5})
        assert planned[0].method == "POST"
        assert planned[0].path == "/api/relay/rest/queues"

    def test_a_step_returning_none_is_omitted_from_the_plan(self):
        with_size = recipes.plan(SIMPLE, {"name": "s", "size": 5})
        without = recipes.plan(SIMPLE, {"name": "s"})
        assert len(with_size) == 2
        assert len(without) == 1

    def test_planning_issues_nothing(self):
        # The point of --dry-run: no client is even needed to build a plan.
        recipes.plan(SIMPLE, {"name": "support"})  # would raise if it called out


class TestRun:
    async def test_steps_execute_in_order_and_capture_ids(self):
        client = FakeClient()
        results = await recipes.run(SIMPLE, {"name": "support", "size": 5}, client)
        assert [r.action for r in results] == ["created", "created"]
        assert client.writes() == [("queues", "create"), ("queues", "create")]

    async def test_an_existing_row_is_reused_not_duplicated(self):
        # This is what makes a re-run safe.
        client = FakeClient(existing={"queues": [{"id": "q-9", "name": "support"}]})
        results = await recipes.run(SIMPLE, {"name": "support"}, client)
        assert results[0].action == "reused"
        assert results[0].detail == "q-9"
        assert client.writes() == []

    async def test_ensure_by_none_always_creates(self):
        client = FakeClient(existing={"queues": [{"id": "q-9", "name": "second"}]})
        results = await recipes.run(SIMPLE, {"name": "other", "size": 1}, client)
        # step one is new, step two matches an existing name but opted out
        assert [r.action for r in results] == ["created", "created"]

    async def test_a_failure_stops_the_run(self):
        # A later step almost always depends on an earlier one, so pressing on
        # would bury the error that mattered.
        client = FakeClient(error=RuntimeError("422 unprocessable"))
        results = await recipes.run(SIMPLE, {"name": "support", "size": 5}, client)
        assert results[-1].action == "failed"
        assert "422" in results[-1].detail
        assert len(results) == 1

    async def test_an_unknown_resource_fails_rather_than_silently_skipping(self):
        broken = recipes.Recipe(
            key="broken", title="Broken",
            steps=lambda ctx: [recipes.Step(label="nope", resource="does-not-exist",
                                            body=lambda c: {"name": "x"})],
        )
        results = await recipes.run(broken, {}, FakeClient())
        assert results[0].action == "failed"
        assert "does-not-exist" in results[0].detail


class TestShippedRecipes:
    def test_pbx_is_registered_and_prefix_resolvable(self):
        assert recipes.get("pbx") is recipes.PBX
        assert recipes.get("pb") is recipes.PBX
        assert recipes.get("nope") is None

    def test_pbx_creates_one_extension_per_count_plus_a_dial_plan(self):
        ctx = recipes.coerce_params(recipes.PBX, {"name": "acme", "extensions": "5"})
        planned = recipes.plan(recipes.PBX, ctx)
        assert len(planned) == 6
        assert sum(1 for p in planned if p.step.resource == "sip") == 5
        assert planned[-1].step.resource == "swml"

    def test_pbx_numbers_extensions_from_the_start_value(self):
        ctx = recipes.coerce_params(
            recipes.PBX, {"name": "acme", "extensions": "2", "start_extension": "2000"}
        )
        planned = recipes.plan(recipes.PBX, ctx)
        assert [p.body["username"] for p in planned[:2]] == ["2000", "2001"]

    def test_every_shipped_recipe_step_targets_a_resolvable_operation(self):
        # A recipe naming a resource or op that does not resolve is a command
        # that fails at the first step. Catch it here, not on someone's project.
        for recipe in recipes.RECIPES:
            ctx = {f.name: (2 if f.kind == "int" else "probe") for f in recipe.params}
            for planned in recipes.plan(recipe, ctx):
                assert planned.method != "?", f"{recipe.key}: {planned.path}"
                assert "{" not in planned.path.split("/")[-1] or planned.method != "POST"
