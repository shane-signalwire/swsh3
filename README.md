# `sw` — the SignalWire command line

`sw` is one binary with three faces:

- a **scriptable CLI** — `sw numbers list`, `sw calls dial`, `sw send create` — every
  one of which speaks `--json` so it pipes into `jq`;
- a **live cockpit** — `sw sh`, a full-screen terminal app that browses, edits and
  watches every resource on the project, with a real SIP softphone in it;
- a **callback sink** — `sw listen`, which tunnels your status callbacks to your
  own terminal and puts the original URLs back when you quit.

> **Alpha.** This is an internal preview release. The command surface is stable
> enough to script against, but expect rough edges, and read
> [Known limitations](#known-limitations) before you rely on anything.

---

## Contents

- [Install](#install)
- [Authenticate](#authenticate)
- [Command line](#command-line)
  - [The shape of a command](#the-shape-of-a-command)
  - [Finding a row without knowing its id](#finding-a-row-without-knowing-its-id)
  - [`--json`, `--raw` and `--profile`](#--json---raw-and---profile)
  - [Following a number's routing](#following-a-numbers-routing)
  - [Calls](#calls)
  - [`sw api` — the escape hatch](#sw-api--the-escape-hatch)
  - [`sw listen` — receiving callbacks](#sw-listen--receiving-callbacks)
  - [Recipes](#recipes)
  - [Tab completion](#tab-completion)
- [The cockpit: `sw sh`](#the-cockpit-sw-sh)
  - [Getting around](#getting-around)
  - [Acting on a row](#acting-on-a-row)
  - [Reading a row three ways](#reading-a-row-three-ways)
  - [Calls, and the phone panel](#calls-and-the-phone-panel)
  - [Copying text off the screen](#copying-text-off-the-screen)
- [The resource surface](#the-resource-surface)
- [Development](#development)
- [Known limitations](#known-limitations)

---

## Install

Python 3.11 or newer.

```bash
git clone https://github.com/signalwire/swsh3.git
cd swsh3
python3 -m venv .venv
.venv/bin/pip install -e .
```

One console script is installed, `sw`:

```bash
.venv/bin/sw --version          # sw 3.0.0
```

Put `.venv/bin` on your `PATH`, or install it globally with
[uv](https://docs.astral.sh/uv/):

```bash
uv tool install .
```

### The SIP softphone is optional

The cockpit's phone is a real registered SIP endpoint with real audio, built on
`baresip-python`. It is a pre-release binary wheel, so it is an **extra** rather
than a dependency — everything else in `sw` works without a SIP stack:

```bash
pip install --pre 'swsh[sip]'
```

Note the name: the **distribution** is `swsh`, the **command** is `sw`. `sw` on
PyPI is an unrelated package by someone else, and `pip install 'sw[sip]'` will
quietly install that instead.

---

## Authenticate

`sw` needs a project id, an API token and a space. There are four places it can
find them, checked in a fixed order:

| Priority | Source | Use it for |
| --- | --- | --- |
| 1 | `--profile NAME`, or `SWSH_PROFILE` | Reaching into another space for one command |
| 2 | Environment variables | CI, containers, a shell you set up deliberately |
| 3 | The default stored profile | Your day-to-day space |
| 4 | A `.env` file in the working directory | A project directory that always means one space |

The usual path is a stored profile:

```bash
sw login                            # prompts for project, token, space
sw login --name scratch             # a second profile
sw profile list                     # which ones exist, and which is in effect
sw profile use scratch              # make one the default
sw whoami                           # verify, and say where each value came from
```

`sw whoami` reports the **tier** each value came from, which is the answer to
every "my profile is being ignored" moment.

Credentials go into a `0600` file under your home directory (`sw profile path`
prints it). Set `SWSH_USE_KEYRING=1` to mirror the token into the OS keyring as
well.

The environment variables, if you prefer them:

```bash
export SIGNALWIRE_PROJECT_ID=...
export SIGNALWIRE_TOKEN=...
export SIGNALWIRE_SPACE=acme.signalwire.com
```

---

## Command line

### The shape of a command

Noun first, verb second. Every resource is a command group named for the thing
it holds, and the verbs under it are the same five everywhere:

```bash
sw numbers list
sw numbers get +15551234567
sw sip create --name support --username support
sw swml update <id> --set name="after hours"
sw queues delete <id>
```

A few resources rename a verb where the platform's own word is better — buying a
phone number is `sw numbers buy`, and giving one back is `sw numbers release`.
Beyond the five verbs, a resource offers whatever *actions* it has:

```bash
sw numbers assign-e911-address +15551234567 --e911-address-id <id>
sw brands campaigns <brand-id>
sw subscribers tokens <subscriber-id>
```

`sw <group> --help` lists what a group can do; `sw <group> <verb> --help` names
every field the verb takes.

**Omit a required field and `sw` asks for it.** In a terminal, a missing value
opens a prompt, and a field with a known set of values opens a picker — so
`sw sip create` alone is a usable way to make a SIP endpoint. Under `--json`, or
with no terminal attached, a missing value is a hard error instead, so a script
never hangs waiting on a prompt nobody will answer.

Every list takes `--limit/-n` and `--match/-m`:

```bash
sw numbers list -n 200
sw numbers list -m 209            # searches number and name
sw sip list -m support
```

The command's `--help` names the fields `--match` will look in.

### Finding a row without knowing its id

Nobody remembers a phone number's uuid. They remember the number, and they named
it. So on `numbers`, **every verb that takes an id also takes a handle** — `get`,
`update`, `release`, and the actions that work on a number:

```bash
sw numbers get "Fax Number"
sw numbers get 2095550183
sw numbers get "(209) 555-0183"
sw numbers update +12095550183 --set name="Support line"
sw numbers release "Fax Number" "Old DID"
```

Matching is case-insensitive and digit-insensitive, so `2095550183`,
`(209) 555-0183` and `+12095550183` all find the same row. An exact hit wins
outright; several partial hits are an error that names the candidates rather
than guessing.

**`numbers` is the only resource that does this today.** Handle lookup is opt-in
per resource, and it is only turned on where the search has been probed against
a live space — a filter the API quietly ignores returns the whole collection,
and the "match" then resolves to the wrong row, which is worse than a 404.
Everywhere else `get`, `update` and `delete` want the id, and `--match/-m` on the
listing is how you find it:

```bash
sw sip list -m support            # find it
sw sip get <the id from that row> # then act on it
```

Anything shaped like an id (a uuid, or a compatibility SID) is used directly and
costs no lookup. Every command prints what it resolved, so the id is there to
paste into the next one:

```
updated Fax Number (b5cf76f4-1d3e-4a90-9c22-6b0c1f8e7a45)
```

`delete` resolves **every** identifier before it asks and before it sends
anything, and the confirmation prints each `handle → id` pair — because
"release 2 phone numbers?" is not a question anyone can answer.

### `--json`, `--raw` and `--profile`

These belong to commands, not to `sw` itself, and their order does not matter:

```bash
sw numbers list --json --profile scratch      # works
sw numbers list --profile scratch --json      # works
sw --json numbers list                        # usage error, on purpose
```

The two output flags answer different questions:

- **`--json`** is what `sw` made of the answer: rows lifted out of the list
  envelope, `--limit` applied, a call flattened to the fields the registry
  models. This is what you pipe into `jq`.
- **`--raw`** is the body of the one call the command is about, exactly as it
  arrived — envelope, paging links, and every field `sw` does not model. It is
  the answer to "`sw` does not show the field I need" that does not involve
  rebuilding the request by hand.

```bash
sw numbers list --json | jq -r '.[].number'
sw numbers get "Fax Number" --raw | jq '.'
```

`--raw` implies `--json`. A command with no single response — `sw recipe run`,
for instance — refuses `--raw` *before* it runs anything, rather than doing the
work with the output suppressed and then admitting it cannot answer.

Without `--json`, a single row prints as a field/value table rather than a blob:
every key the API sent, in the order it sent them, `-` for a null and `""` for an
empty string so "unset" and "set to empty" stay distinguishable. Timestamps are
converted to your local time and named (`2026-08-12 12:39:53 EDT`).

### Following a number's routing

A phone number's row does not say what happens when it rings. It keeps every
pointer it has ever had — a number on `relay_script` still carries the
`call_laml_application_id` from a cXML application it used last year — and only
`call_handler` says which one is live.

```bash
sw numbers get +15551234567 --full
```

`--full` resolves that: it follows the live handler to the Fabric resource it
points at, pulls that resource's configuration inline, resolves a hosted bin URL
back to the SWML or cXML it holds, and reports the settings belonging to *other*
handlers as `NOT IN USE` rather than dropping them.

Fetching a URL that points off the space is done with a **fresh unauthenticated
client** — following somebody's webhook with your project token would hand them
the keys to the space.

### Calls

```bash
sw calls list                       # newest first, whichever engine carried them
sw calls dial --to +15551234567 --from +15559876543 --url https://example/swml
sw calls show <call-id>
sw calls play <call-id> --text "your table is ready"
sw calls digits <call-id> --digits 1234
sw calls record <call-id>
sw calls transfer <call-id> --to ...
sw calls hangup <call-id>
```

Live calls come from the **voice log**, not the compatibility `Calls` list: the
compatibility list only holds LaML legs, so a SIP endpoint dialling out through
SWML, a call flow, an AI agent or a video room never appears in it. The voice log
lists every leg from `initiated` onward.

### `sw api` — the escape hatch

Anything the registry does not model is still one command away, including the
whole Compatibility/LaML API. An operation id resolves its own method and path
from the bundled catalog, and `{AccountSid}` fills from your profile.

```bash
sw api --list                                   # every operation
sw api --list compatibility-api                 # scoped to one API
sw api /api/relay/rest/phone_numbers | jq '.data | length'
sw api list_subscribers
sw api send_fax -f To=+15551234567 -f From=+15559876543 -f MediaUrl=https://x/f.pdf
sw api delete_fax FX123 -X DELETE --force
sw api create_queue -F MaxSize=50 --dry-run     # print the request, send nothing
```

Output is the response body verbatim. A write prompts for confirmation unless
`--force`; with no terminal it errors instead of hanging.

### `sw listen` — receiving callbacks

```bash
sw listen                           # tunnel, rewrite every number, stream
sw listen -N +15551234567           # just this one
sw listen --no-rewrite              # print the URL, change nothing
sw listen --public-url https://my.tunnel/  # skip ngrok
sw listen --restore                 # undo a rewrite a crashed run left behind
```

It opens a tunnel, points your numbers' status callbacks at it, prints every
callback as it arrives, and puts the original URLs back on exit. The originals
are journalled to disk *first*, so an unclean exit is recoverable with
`--restore`.

### Recipes

A recipe is a job that is a dozen API calls and one sentence to a person.

```bash
sw recipe list
sw recipe run pbx --dry-run         # print the resolved plan, change nothing
sw recipe run pbx --name acme --extensions 4
```

Recipes are **preview**. A recipe never deletes and never diffs: it is an ordered
list of creates with ensure-by-name, so re-running one converges rather than
duplicating. `--dry-run` needs no credentials and is the reviewable step.

### Tab completion

```bash
sw completion install               # bash, zsh, fish
sw completion status                # which files hold it, if any
sw completion uninstall
sw completion show                  # print the script without installing
```

Completion invokes `sw` by name, so `sw` has to be on your `PATH` in a *new*
terminal. Installed with `pip install -e .` into a project venv it is not, and
`completion install` warns when it detects that.

---

## The cockpit: `sw sh`

```bash
sw sh
```

A full-screen terminal app over the same registry the CLI uses. It opens on a
dashboard — which space and profile are in play, and eight counts of what the
project holds — not on a table, because on a quiet project an empty table is the
worst first screen an app can have.

A bare `sw` prints help and does **not** open the cockpit. `sw` runs in pipes, CI
jobs and Dockerfiles, where a full-screen app hangs or dies, and the help listing
is the only place the command tree advertises itself.

### Getting around

| key | does |
| --- | --- |
| `?` | jump list: every resource, by name |
| `:` | command bar — `:numbers`, `:calls`, `:sip` |
| `escape` | back one level: a drill to its list, a list to the dashboard |
| menu bar | the resource groups, as dropdowns |
| `r` | refresh |
| `q` | quit |
| `ctrl+p` | profiles: switch space without leaving |
| `j` / `k` | down / up, for vi hands |

### Acting on a row

| key | does |
| --- | --- |
| `enter` | inspect — drill into the row |
| `n` | new |
| `e` | edit |
| `d` | delete (asks first) |
| `x` | more: every action this resource offers beyond CRUD |
| `.` | context actions for the row under the cursor |
| `F` | routing — toggle the detail pane to the resolved routing tree |

Forms are generated from the same field declarations the CLI uses, so every field
gets a real control: a picker where the values are enumerable, a tickbox for a
boolean, a masked box for a password, and an editor that validates locally for a
field that genuinely is a document. `ctrl+s` saves, `escape` cancels.

**A drill does not inherit its parent's CRUD.** Inside `groups > memberships` the
rows are memberships, so `n`, `e`, `d` and `F` are withheld — editing there would
send a well-formed request against the wrong object. Actions that *do* act on a
drill's rows still show.

### Reading a row three ways

`v` cycles the detail pane:

- **fields** — the rendered field/value table;
- **json** — the row `sw` is holding;
- **raw** — that row's own record, fetched from its read route, because a list
  response is usually a summary.

Where there is no read route, the list row *is* the API's answer, and the pane
says so rather than inventing a fetch.

### Calls, and the phone panel

`:calls` is the live calls table, fed by three merged sources — the RELAY tap,
status callbacks and an adaptive poller. Under it rides a phone panel holding two
things that exist to test each other:

- **a SIP device** — a real registered endpoint with real audio, dialling out and
  answering in (needs the `sip` extra);
- **a local AI agent** — built from a prompt, a greeting, a voice and a set of
  skills, served locally, tunnelled, and wired into Call Fabric as a SWML webhook
  plus a SIP address, so a phone can dial it.

| key | does |
| --- | --- |
| `g` | register the device |
| `H` | dial / hang up — one hook, because a phone has one |
| `0`–`9`, `*`, `#` | DTMF while on a call; types into the target box while not |
| `u` | stand up the local agent |
| `a` | dial the agent |
| `h` | hang up the **selected** platform leg |
| `t` `p` `s` `R` | transfer, say, DTMF, record — on the selected leg |
| `f` | show ended calls |
| `c` | clear the feed |
| `y` | copy the phone's diagnostics |

Press `a` and the device dials the agent. Edit the prompt, stand it up, call it,
hear it — that loop is the reason both halves are on one screen, and the phone's
own log lands in the same feed as the platform's call events.

Everything the agent lab creates is deleted again, on teardown *and* on a failed
start.

### Copying text off the screen

A full-screen app turns on mouse reporting, and while that is on the terminal
hands every click and drag to the app instead of using it to select text.

- **`m`** hands the mouse back. Drag and copy as you would over `cat`, then press
  `m` again. A green `SELECT` badge in the status bar shows while it is on.
- **`y`** copies the phone's diagnostics — profile, identity, transport, the
  redacted account line, the last dial target and the feed — to the clipboard
  *and* to a file, naming the path, because neither is reliable alone. The
  password is replaced with `***`.

---

## The resource surface

54 resources across 8 groups, over 15 API families: Fabric, Relay REST,
Compatibility/LaML, video, messaging, datasphere, projects, voice and fax.

```bash
sw docs --list                      # one line per resource
sw docs -o reference.md             # the full reference, in Markdown
```

`sw-reference.md` in this repo is that output, checked in. It is generated from
the registry — the single source of truth behind both the CLI and the cockpit —
so it cannot drift from what `sw` actually does.

Anything not modelled as a resource is still reachable with `sw api`. That is
deliberate: the registry is for what people browse and edit, not a catalogue of
every endpoint.

---

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

.venv/bin/python -m pytest -q            # 800 tests
.venv/bin/ruff check .

python scripts/audit_fields.py           # registry fields vs documented parameters
python scripts/audit_secrets.py --check  # credentials and environment config on disk
```

`audit_secrets.py --check` is a gate and passes. `audit_fields.py` is a **report**,
not a gate: 30 of 38 writable resources declare fewer fields than the API
documents, deliberately — a brand's 13-parameter vetting form is not a thing to
put behind `sw brands create`. Read it before adding fields, and treat
`--check` as "show me the drift", not as CI.

There is no live-API test. The live probes are separate, and are how a guess
becomes a verified fact:

```bash
python scripts/verify_registry.py        # probe every resource against a live space
python scripts/verify_softphone.py       # a real call over loopback, no network
python scripts/probe_dial_uri.py         # which dial-target shapes the stack accepts
python scripts/probe_invite_uri.py       # what actually goes on the wire
python scripts/probe_sip_edges.py <domain>   # which SIP edges answer, per transport
```

`test_plans/` holds manual QA checklists, one per command group.
[`docs/verification.md`](docs/verification.md) sets out what each kind of check
actually proves and what has been confirmed against a live space;
[`docs/field-audit.md`](docs/field-audit.md) is generated
(`python scripts/audit_fields.py --markdown`).

### Adding a resource

Add one entry to `RESOURCES` in `swsh/resources.py`. Do not write a command
module, a screen or a formatter — one entry yields the CLI verbs, the cockpit
screen, the create/edit form, shell completion, a `sw docs` section and a
coverage-gate row.

Before adding one, ask whether `sw api` is enough. A one-off call, or an endpoint
used by one script, does not need a registry entry.

### Layout

```
swsh/
  cli.py          Typer app; every registry resource becomes a command group
  resources.py    THE REGISTRY — 54 resources, 52 of them spec-driven REST
  routing.py      get --full: resolve a row's live handler and follow it
  recipes.py      guided composites
  client.py       one client; invoke(resource, op, ...) dispatches by transport
  spec.py         the bundled OpenAPI catalog (332 operations, 15 APIs)
  coverage.py     the completeness gate
  config.py       profiles and credential precedence
  softphone.py    the registered SIP device
  agentlab.py     a local AI agent, tunnelled and wired into Call Fabric
  events/         RELAY tap, webhook sink, adaptive poller, bus, tunnel
  tui/            the cockpit
scripts/          audits and live probes
tests/            pytest; respx for HTTP, app.run_test() for the cockpit
test_plans/       manual QA checklists
```

The API catalog is checked in (`swsh/spec_catalog.json`), so there is no runtime
dependency on the spec repo. To regenerate it you must compile the OpenAPI first
— see `scripts/build_catalog.py`.

---

## Known limitations

- **Alpha, for internal distribution.** Not published to PyPI.
- **The SIP softphone is an optional pre-release wheel** and is not available on
  every platform. Everything else works without it.
- **Recipes are a preview.** `sw recipe run` is unverified against a live space;
  use `--dry-run` first.
- **`sw listen --verify-signatures` is unverified.** The HMAC validation path has
  not been confirmed against live callbacks.
- **The Compatibility/LaML API is deliberately not modelled** as resources. It is
  reachable in full through `sw api`.
- **`sw cxml list` can return a 500** server-side if the project holds an orphaned
  `cxml_script`. `sw` surfaces the error rather than hiding it.
- **`sw orders list` cannot run on its own.** Its route is
  `/registry/beta/campaigns/{id}/orders`, so it needs a campaign id that the
  generated command has nowhere to take. `sw orders get <order-id>` works.
  Reach the listing with `sw api list_orders -p id=<campaign-id>` meanwhile.
- **`sw gateways update` needs the whole SIP configuration.** The platform
  validates that route as a full replace, so a partial `--set encryption=…` is
  refused with `missing_sip_configuration`. Resend `name`, `uri`, `encryption`,
  `ciphers` and `codecs` together.
- **Handle lookup is `numbers` only** — see
  [Finding a row without knowing its id](#finding-a-row-without-knowing-its-id).
- **Repeated failed SIP registrations get your source IP blocked** by the
  platform, which looks exactly like a broken client. Nothing in `sw` retries
  automatically, but do not loop registration attempts by hand;
  `scripts/probe_sip_edges.py` checks for it without adding to the problem.

---

## License

MIT. See [LICENSE](LICENSE).
