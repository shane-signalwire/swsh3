# Changelog

Notable changes to `sw`. Newest first.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
loosely: entries say what changed for someone using the tool, not what moved in
the source.

## [3.0.0] — unreleased

The first release of the merged tool: the cmd2 shell that was `swsh` through
2.0 and a Typer/Textual prototype built around a declarative resource registry,
as one project shaped like `gh`. One console script, `sw`; the interactive shell
is `sw sh`.

### Fixed

- **A listing is the whole collection, not its first page.** `--limit` was a
  slice of whatever one request returned, so `sw logs list -n 200` answered with
  50 rows and no sign there were more. Worse, `--match` sifted that single page:
  `sw resources list -m "Test AI API"` reported *no rows* for a resource that
  existed further down. Listings now follow the API's paging until the limit is
  met, and a search walks the whole collection before answering.
- **Four commands that could never succeed are gone.** `sw orders list|create`
  and `sw campaigns list|create` answered `needs a resource id` on every
  invocation — their routes hang off a parent the command had nowhere to accept.
  Both listings are reached through the parent instead (`sw brands campaigns
  <brand-id>`, `sw brands orders <campaign-id>`).
- **`sw sipprofile get` demanded an id** for a record whose route has none.
- **Seven resources sent requests the platform could only reject**, live-probed
  with the new `scripts/probe_fields.py`: `relayapps` needs `name`, `connectors`
  needs `token`, `datasphere` needs `url`, `domains` needs `identifier`, `vconf`
  needs `display_name`, and a call flow is created by `title`, not `name`.
- **Three settings were accepted and silently dropped.**
  `videorooms --set max_participants=7` produced a room with the default
  capacity of 20 — the field is `max_members`. A video conference has no numeric
  cap at all; it has `size` (`small|medium|large`). The SIP profile's `username`
  and `default_caller_id` do not exist on that record; the caller id is
  `default_send_as`.
- **Errors are readable.** A validation failure arrived as a Python repr of a
  list of dicts. Each problem is now a line led by the field name, with the
  platform's doc links as hints underneath. 403, 409 and 429 say what they are
  instead of collapsing to `request failed`.
- **`--json` no longer emits ANSI into a pipe** when `FORCE_COLOR` is set, which
  made `jq` answer `Invalid numeric literal`.
- **A list table never truncates an identifier.** Ids and timestamps are pinned
  to their content width; everything else gives up the space.
- **Timestamps read the same everywhere** — ISO-8601, ISO with milliseconds and
  RFC 2822 all render as local time.
- **An empty collection says `no rows`** rather than drawing a row of dashes,
  which was indistinguishable from one record whose every field is null.
- **The SDK transport has a timeout.** It had none, so those calls could hang
  for as long as the far end held the socket open.

### Added

- **Any named row can be addressed by name**: `sw sip get fsdemo`,
  `sw swml delete "after hours"`. 36 of 54 resources; the rest are logs, minted
  tokens and drills, which have no name to type.
- **`--sort`, `--desc`, `--columns` and `--csv`** on every listing. `--sort`
  orders the whole collection, and `--columns` reaches fields the default table
  leaves out.
- **`--timeout` and `SWSH_TIMEOUT`**, and automatic retry of 429 and 5xx
  responses with backoff, honouring `Retry-After`. A create is never replayed.
- **`/` filters the rows on screen in the cockpit**, and **`?` shows every key**
  grouped (the resource jump list moved to `ctrl+r`).
- **`sw sh` opens on the profile form when there are no credentials**, instead
  of exiting before the app that could collect them was built.
- **`sw login` verifies the three values** against the platform before storing
  them, and says where an API token comes from.
- **Shell completion installs itself** on the first interactive run, says which
  file it wrote and how to undo it. `SWSH_NO_COMPLETION_INSTALL=1` opts out.
- **The SIP softphone ships with `sw`** rather than behind an extra.
- `scripts/probe_fields.py` — asks the platform which fields a create really
  needs, and deletes what it made.
- CI on Python 3.11 through 3.14: tests, lint, and the secret audit.

### Removed

- **Recipes.** `sw recipe` and its `--set`/`--dry-run` are gone; the guided
  multi-step setups were a preview that had not been verified against a live
  space.
- The second console script, `swsh`, and `sw tui`. The cockpit is `sw sh`.

### Known limitations

See [Known limitations](README.md#known-limitations) in the README.
