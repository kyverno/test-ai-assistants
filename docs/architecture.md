# Architecture

**Status: skeleton only.** `distribution.yaml` / `SOUL.md` / `config.yaml` exist
and are verified against Hermes' real config schema (see "How the toolset
allowlist is actually verified" below). `skills/kyverno-context`,
`skills/pr-queue`, and `skills/pr-actions` — referenced throughout this doc and
the README — do not exist yet. Nothing below describes working behavior; it
describes the design those skills still need to implement.

kyverno-assistant is a [Hermes profile distribution](https://hermes-agent.nousresearch.com/docs/user-guide/profile-distributions):
`distribution.yaml` + `SOUL.md` + `config.yaml` + `skills/` + `hooks/`, git-installed
by a maintainer with `hermes profile install`, updated with `hermes profile update`.
It's a single, on-demand agent process talking to one maintainer over Slack/CLI —
not a webhook-triggered service (that was the previous, abandoned `kyctrl` design;
see `docs/archive/kyctrl-phase0-notes.md`). This is also a deliberate divergence
from where the wider ecosystem is heading — GitHub's own Agentic Workflows
(technical preview, Feb 2026) treats webhook/Actions-triggered issue and PR
automation as the default pattern. v1 chooses human-invoked-only on purpose,
matching SOUL.md's "guest doing mechanical work" framing; any move to
triggered/autonomous operation is a v2+ decision, not an oversight.

MCP servers (GitHub, Slack) are declared under `config.yaml`'s `mcp_servers:`
key, not a separate `mcp.json` — Hermes reads MCP server definitions from
`config.yaml` itself ([MCP Config Reference](https://hermes-agent.nousresearch.com/docs/reference/mcp-config-reference));
a standalone top-level `mcp.json` (Claude-Desktop-style) is an *import* format
for `hermes import-agent claude-code`, not something a profile distribution's
install reads on its own. An earlier draft of this repo had the MCP servers in
a sibling `mcp.json`, which a real `hermes profile install` would most likely
never load.

## What it can and can't do

It can read anything on `KYVERNO_REPO` (PRs, diffs, reviews, labels, CODEOWNERS,
milestones), read the configured Slack channel, and — using the maintainer's own
`GITHUB_TOKEN` — add labels, post comments, request changes, approve reviews, and
rebase a branch on instruction.

**It cannot merge a PR.** There is no merge tool anywhere in the toolset — the
same tool-absence enforcement kyctrl used, carried forward as a principle even
though the rest of that design was abandoned: don't rely on a prompt
instruction to withhold a privileged action, withhold the tool. This is
enforced in three independent layers (see below), not one file. Merge is
deferred to v2, where it should be gated behind a GitHub Actions workflow
triggered by a specific comment (kyctrl's original pattern — see the archive
notes) rather than given to the agent process directly.

## How the toolset allowlist is actually verified

`config.yaml`'s header comment names the three layers; here's what backs each
one and how confident to be in it, so a future edit doesn't quietly break an
unverified assumption:

1. **`mcp_servers.github.env.GITHUB_EXCLUDE_TOOLS`** — the upstream
   `github-mcp-server` container's own `--exclude-tools` flag, which its
   `--help` output documents as disabling tools "regardless of other
   settings." **Empirically tested**, not just read from docs: ran the real
   `ghcr.io/github/github-mcp-server` container, did an MCP `initialize` +
   `tools/list` handshake, and confirmed the tool list it returns with this
   repo's exact `GITHUB_EXCLUDE_TOOLS` string is character-for-character the
   31 tools in `tools.include` — no more, no less. Also confirmed the
   *default* toolset (no `GITHUB_TOOLSETS` set) is missing every alert/CI
   tool this profile needs (`list_code_scanning_alerts`,
   `list_dependabot_alerts`, `actions_list`, `get_repository_tree`, `list_label`,
   ...) — hence `GITHUB_TOOLSETS: "all"` plus the exclude list, rather than
   trying to name exact toolset groups and risking a silent gap.
2. **`mcp_servers.github.tools.include`** — Hermes' own per-tool filter,
   matched against raw (unprefixed) tool names per the
   [MCP feature doc](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp).
   **Doc-verified, not live-tested against Hermes itself** (no live Hermes
   install was run in this pass) — trust layer 1's empirical result over this
   one if they ever disagree.
3. **`hooks.pre_tool_call` → `hooks/block-dangerous-tools.sh`** — a shell
   hook, `matcher`-scoped to tool names matching `merge|delete_repo|force_push`,
   with `fail_closed: true`. **Corrected during review, not trusted on first
   pass**: an earlier version used `hooks: [{event: ..., command: ...}]`
   (wrong shape — the real schema is a mapping keyed by event name, e.g.
   `hooks: {pre_tool_call: [...]}`) and read tool name from a
   `$HOOK_TOOL_NAME` env var that Hermes never sets — it pipes the event as
   JSON on **stdin**, always. The env-var version had been "unit-tested in
   isolation" by exporting `HOOK_TOOL_NAME` and running the script directly,
   which passed — but that test exercised an interface Hermes never actually
   calls, so it gave false confidence; fed the real stdin shape, the old
   script silently approved every tool call, including a merge. Also: in
   Hermes' own vocabulary `{"action": "approve"}` means *escalate to the
   human-approval gate*, not "allow" (unlike Claude Code's meaning of the
   same word) — a naive fix of only the stdin bug would have made every
   tool call require manual approval instead. Fixed now: schema corrected
   against [the real hooks doc](https://hermes-agent.nousresearch.com/docs/user-guide/features/hooks)
   (exact YAML shape, JSON wire protocol, and fail-open/fail-closed table
   all read directly, not summarized), script reads `tool_name` via `jq`
   from stdin, and — since the `matcher` means every invocation is already
   a match — always blocks; there's no non-blocking branch left to get
   wrong. Verified by piping a real `pre_tool_call`-shaped JSON payload to
   the script directly and confirming the block JSON comes back (see repo
   history). Still never exercised inside a running Hermes process, and
   shell hooks fail open by default — which is exactly why `fail_closed:
   true` is set, not omitted.

Slack is narrower in scope (only `conversations_history` and
`conversations_add_message` are ever wanted) and gets one server-side layer:
both tools are listed in `SLACK_MCP_ENABLED_TOOLS`, with
`SLACK_MCP_ADD_MESSAGE_TOOL=${SLACK_HOME_CHANNEL}` doing the actual channel
scoping. This was verified live against a real, fully-scoped bot token and
corrected twice in the process:

- `korotovsky/slack-mcp-server` validates its token at process startup and
  calls `log.Fatal` on failure, before ever reaching the MCP handshake — an
  expired/wrong `SLACK_MCP_XOXB_TOKEN` means the container never starts, not
  that it starts with degraded capability. Less obviously: the server also
  fetches *all four* Slack channel types (`public_channel`, `private_channel`,
  `mpim`, `im`) in one combined call at boot regardless of what this profile
  actually uses, and fails that same fatal way if the token is missing the
  scope for *any one* of them — so the bot token needs `channels:read`,
  `groups:read`, `mpim:read`, and `im:read` even though this profile only
  ever reads one public channel. `.env.example`'s scope list didn't originally
  include the last three; confirmed by running the real container directly
  and reading its fatal error, not by inspecting docs.
- `conversations_add_message` must be listed in `SLACK_MCP_ENABLED_TOOLS`
  alongside `conversations_history`, not left out of it. The server's own
  tool *registration* gating and its per-call channel-restriction check are
  two independent code paths (confirmed by reading
  `pkg/handler/conversations.go`): registration requires the tool to be
  named in `SLACK_MCP_ENABLED_TOOLS` once that variable has any content at
  all (an earlier, unverified assumption held that leaving it out was
  required to keep the channel scoping — that assumption produced a real
  bug, live-confirmed: only 1 of 2 tools registered), while the "without
  channel restrictions" behavior actually depends only on
  `SLACK_MCP_ADD_MESSAGE_TOOL` being empty at call time, which it never is
  here (it's always `${SLACK_HOME_CHANNEL}`). Both tools registering with
  the channel scoping intact is a config the server supports; it doesn't
  need this profile to omit the write tool from the enabled-tools list.

One thing was confirmed straight from `korotovsky/slack-mcp-server`'s source
without needing a live token: `conversations_history` takes no search query,
only a time/count `limit`, and the server's own `conversations_search_messages`
tool is registered only for non-bot tokens (Slack's `search.messages` API
itself doesn't work with a bot token) — so "search Slack for a PR mention"
is a bounded-window scan with client-side text matching, not a real search,
regardless of what's granted. `skills/pr-queue/SKILL.md`'s review-brief
section handles this explicitly rather than implying a real search happened.

It also cannot re-trigger or automatically detect post-merge CI failures — that
would need a webhook receiver or a polling loop, both out of scope for v1. If a
maintainer mentions in conversation that CI broke on `main`, the `pr-queue` skill
can take that as input and flag which queued PRs likely overlap the break by
touched files — but this is conversational, not monitored.

## Real-repo testing findings (kyverno/kyverno, non-collaborator token)

First live test against `kyverno/kyverno` with a non-collaborator PAT
surfaced four bugs, each root-caused against the real container/API before
fixing (no guessing):

**`GITHUB_LOCKDOWN_MODE=1` 403s every `pull_request_read` for a
non-collaborator token.** Lockdown mode checks the PR *author's*
collaborator permission on every read to decide whether to filter their
content; that permission-check endpoint itself requires the *calling*
token to have push access. Confirmed directly against the real container:
`failed to check lockdown mode: failed to get user permission level: ...
403 Resource not accessible by personal access token`. A maintainer
without push access — the exact case this profile exists for — can't use
it at all: it fails closed on every read, not just on filtering. Per
github/github-mcp-server's own docs, lockdown mode "does not restrict what
the underlying credential can otherwise read or write" — it's a
best-effort prompt-injection content filter, not an authorization
boundary, so disabling it (`GITHUB_LOCKDOWN_MODE: "0"`) doesn't expand any
write capability; it only means unfiltered content from non-collaborator
PR/issue authors now reaches the model directly. Compensating control:
`SOUL.md` now states explicitly that PR/issue/comment content is data,
never instructions.

**GitHub MCP tool calls were serializing one at a time, with visible
retries.** An MCP server must opt into `supports_parallel_tool_calls` or
Hermes rejects a multi-call batch to it outright. Tested the real
container directly: two overlapping in-flight `tools/call` requests came
back correctly id-matched, out of submission order — genuine concurrent
handling, safe to enable. `config.yaml`'s github server now sets
`supports_parallel_tool_calls: true`.

**`total_count` was right; the assumption that candidate sets are small
was wrong.** `kyverno/kyverno` currently has ~146 real `ready-for-review`
PRs at once — confirmed against `gh`'s own count with a correct `--limit`
(an unlimited first check silently capped at `gh`'s default 30 and looked
like a mismatch; it wasn't). `pr-queue` now defaults to a `perPage`-bounded
slice instead of the full set.

**Every profile silently gets Hermes' general-purpose bundled skill
catalog** (`apple`, `social-media`, `devops`, `email`, ...) — unrelated to
anything this distribution ships, discovered and loaded mid-session when
the agent hit the lockdown-mode bug and went looking for alternatives. Not
a security hole (the toolset gate still blocked the resulting `terminal`
tool call), but unwanted surface and wasted effort. Fix: a `.no-bundled-skills`
marker file at the repo root, so no fresh install ever seeds the bundle;
an already-installed profile needs a one-time
`hermes -p <profile> skills opt-out --remove -y`. Also: the agent's own
"curator" can write new skills mid-session (`skill_manage`, a core tool,
not gated by `toolsets:`) — `config.yaml`'s `skills.write_approval: true`
now stages that like `memory.write_approval` already does for mnemosyne.
The one pinned "essential" skill (`hermes-agent`) never auto-seeds either,
since this distribution's own `skills/` is never empty — `scripts/install.sh`
now forces it via `hermes skills reset hermes-agent --restore --yes`.
`${KYVERNO_REPO}` in `SKILL.md` never resolved either — Hermes only
substitutes `${HERMES_SKILL_DIR}`/`${HERMES_SESSION_ID}` (hardcoded regex,
`agent/skill_preprocessing.py`) — `scripts/install.sh` now does this
substitution itself after credentials are confirmed.

## How `sequence_prs` ships and why it uses CP-SAT

`plugins/kyverno-sequencer/` is a bundled Hermes plugin, not a skill — it
registers one tool, `sequence_prs`, that computes a candidate merge order
deterministically from PR metadata `pr-queue` has already fetched. Two
things about it were verified directly against the installed Hermes source
(`~/.hermes/hermes-agent`), not assumed from the distribution docs:

1. **It ships with zero extra packaging step.** `distribution.yaml` here has
   no `distribution_owned:` key, so `hermes_cli/profile_distribution.py`'s
   `_owned_entries` takes its "legacy: no allowlist" branch — the *entire*
   repo payload gets copied on `hermes profile install`/`update`, not just
   `SOUL.md`/`config.yaml`/`mcp.json`/`skills`/`cron` (the `DEFAULT_DIST_OWNED`
   tuple, which only applies once an author opts into an explicit
   `distribution_owned:` allowlist). A `plugins/` directory at the repo root
   rides along automatically.
2. **It's discovered automatically, per-profile, with no env var.** Hermes'
   plugin loader scans `$HERMES_HOME/plugins/<name>/`
   (`hermes_cli/plugins_discovery.py`: `user_dir = get_hermes_home() / "plugins"`),
   and `get_hermes_home()` is context-local per active profile — for the
   installed `kyverno` profile this resolves to
   `~/.hermes/profiles/kyverno/plugins/kyverno-sequencer/`. This is a
   **different** mechanism from Hermes' CWD-relative `./.hermes/plugins/`
   "project plugins" path, which is opt-in-only
   (`HERMES_ENABLE_PROJECT_PLUGINS=1`) and flagged in Hermes' own source
   (`hermes_cli/web_server_dashboard.py`) as attacker-controlled surface
   since it ships with whatever directory the CLI happens to be run from —
   not used here. Plugins are still opt-in at the config level, though:
   `config.yaml`'s `plugins.enabled:` must name `kyverno-sequencer`
   (confirmed: `_get_enabled_plugins` treats this as an allow-list, same as
   the existing `mnemosyne` entry), and its tool still needs an explicit
   toolset grant like any other tool here — bundled isn't auto-trusted.

**Why CP-SAT, not a plain topological sort.** Hard precedence (stacked
branches, generated-file input-before-output, interface
definer-before-implementer, dependency-usage) is a genuine DAG problem —
`sequencer.py` builds it and runs Kahn's-algorithm cycle detection exactly
as a plain sort would. But the *soft* priorities (milestone urgency, age,
PR size, e2e-gate risk avoidance, review-readiness) don't reduce to a
lexicographic tie-break — they trade off against each other (a
milestone-critical large PR vs. an old, milestone-irrelevant small one),
which makes "rank subject to precedence, minimizing a weighted sum" the
real problem shape: precedence-constrained weighted completion-time
scheduling, NP-hard for a general DAG, and exactly what CP-SAT solves
(`AddAllDifferent` + `Add(rank[i] < rank[j])` per edge +
`Minimize(weighted linear sum)`) — fast and exactly, not approximately,
given the small PR counts here.

**The dependency isn't auto-installed by Hermes** — plugins ship as plain
copied Python source; a plugin's `requirements.txt` is audit surface only
(confirmed directly in Hermes' `hermes_cli/security_audit.py`: "Plugins
typically don't install into the venv"). `scripts/install.sh` is this
repo's own script, not Hermes', so it installs `ortools` automatically as
one more prerequisite check alongside Docker — no manual step for a
maintainer who uses that script. `sequencer.py` falls back to a stdlib
greedy weighted-priority heuristic (same weights, not globally optimal)
when `ortools` genuinely isn't importable, so the tool never hard-fails
over the optional dependency; the returned `"solver"` field says which
path actually ran.

## Why queue reasoning has to know about codegen and CI structure

Two facts about the real `kyverno/kyverno` build, confirmed directly against its
`Makefile` and `.github/workflows/` rather than assumed:

- Anything under `api/**` fans out to generated code
  (`codegen-api-register` → `zz_generated.register.go`,
  `codegen-api-deepcopy` → `zz_generated.deepcopy.go`) plus clientset/lister/
  informer regeneration and CRD regeneration (`config/crds`). Two open PRs that
  both touch `api/**` will conflict on the *generated* files even if their own
  diffs don't overlap.
- The expensive test suite — `tests-conformance.yaml` (Chainsaw-style, matrixed
  across 3 k8s versions), the 12-way-sharded policy-library suite, k6, perf —
  only runs on `push` to `main`/`release-*` via `check-tests.yaml`, **never on
  `pull_request`**. The first bad interaction between two merged PRs lands on
  `main` undetected. `e2e-gate.yaml`, live on `kyverno/kyverno` today, turns
  that into a reactive block rather than an open door: once that suite fails,
  a required "E2E Gate" status goes red on every open PR targeting the broken
  branch until the tracking issue closes or the fixing PR carries
  `e2e-gate-bypass` — so a single bad interaction stops the queue rather than
  letting more PRs stack on top of it.

Because of this, `pr-queue`'s ranking isn't just label/age/milestone sorting — it
has to reason about generated-file conflicts, stacked PRs, and per-PR post-merge
CI risk explicitly, checking whether `e2e-gate` is currently active for the
target branch, and say so in its output. See `skills/kyverno-context/SKILL.md`
for the codegen/CI reference knowledge and `skills/pr-queue/SKILL.md` for how it's
used.

## Why labels and CODEOWNERS are never hardcoded

`KYVERNO_REPO` can point at `kyverno/kyverno` or at the sandbox repo this
project tests against, and each has its own label set and CODEOWNERS file.
Any skill that hardcodes label names will be wrong the moment it points at
the other one. So `kyverno-context` resolves labels and CODEOWNERS live (`gh
label list`, reading
`CODEOWNERS`) against whatever `KYVERNO_REPO` is configured to, and caches the
result — it never assumes it already knows a repo's conventions.

## Maintainer questions are open-ended — skills aren't scripts

A maintainer can ask this agent anything about the queue's state, not just
the fixed set of actions listed above. `pr-queue`/`pr-actions` should not be
written as a fixed procedure per anticipated question (that list is
unbounded) — they should give the agent the right tools, the fixed facts
that don't change per-question (codegen fan-out, CI split), and one
generalizing instinct: when something about the repo's own state or
conventions is unknown, go look and cite it, don't guess. This is the same
principle as "labels and CODEOWNERS are never hardcoded" above, just
extended past labels/CODEOWNERS to repo docs and arbitrary questions.

Concretely: `kyverno/kyverno` already has whatever docs it has (`AGENTS.md`,
`CONTRIBUTING.md`, `docs/**`, ...) — nothing needs authoring. `search_code`
(`config.yaml`'s `mcp_servers.github.tools.include`) finds and reads them on
demand, scoped to what a specific question needs, rather than eagerly
preloading every doc every session. `search_code` is not automatically
scoped to `KYVERNO_REPO` — it searches all of GitHub unless the query
includes `repo:${KYVERNO_REPO}`; every skill using it must include that
qualifier explicitly.

`search_code` also approximates blast-radius reasoning ("what calls this,
what would this break") via text search — weaker than a real call graph
(misses interface-based indirection in Go), but needs no new
infrastructure. A dedicated code-graph MCP server is a plausible v2 addition
if real maintainer use shows text search isn't enough, but per the
validation plan below, that's a decision for after v1 is used for real —
not before.

## `config.yaml`

The toolset is a hand-picked allowlist, not the raw GitHub/Slack MCP toolsets:
list/get PRs and their diffs, list reviews, list milestones, list labels, read
CODEOWNERS, add label, post PR comment, request-changes review, approve review,
update/rebase branch, Slack channel history read, Slack post message. No
`merge_pull_request` equivalent, and no generic shell/`gh`-command escape hatch
that could reach one indirectly. See "How the toolset allowlist is actually
verified" above for what backs that claim.

## Two separate Slack credential consumers

There are two independent Slack integrations here, easy to conflate because
they reuse the same bot token:

- **Hermes' own `platforms.slack` adapter** — how the maintainer talks to the
  agent (mentions, DMs). Uses `SLACK_BOT_TOKEN` + `SLACK_APP_TOKEN` over
  Socket Mode (a WebSocket connection, no public endpoint needed) via
  Hermes' built-in Bolt integration.
- **The `slack` MCP server** (`korotovsky/slack-mcp-server`) — a *tool* the
  agent calls to read `SLACK_HOME_CHANNEL`'s history and post the ranked
  queue into it. Talks to Slack's Web API directly; has no concept of Socket
  Mode or an app-level token at all. It's given `SLACK_BOT_TOKEN` too (as
  `SLACK_MCP_XOXB_TOKEN`), but never touches `SLACK_APP_TOKEN`.

Both need the Slack app's `chat:write` / `channels:history` / `channels:read`
scopes; only the first needs Socket Mode enabled and `app_mentions:read` /
event subscriptions. If Slack replies work but the queue never posts to
`SLACK_HOME_CHANNEL` (or vice versa), check which of the two integrations is
actually failing before assuming it's one bot token problem — it's plausibly
two independent code paths.

A third thing, confirmed live and easy to miss: correct credentials and a
correct `platforms.slack` config are necessary but not sufficient for the
first integration. Hermes runs exactly one gateway *per host*, not one per
profile, as the single inbound process for every profile's messaging
platforms — `kyverno chat` only starts a foreground CLI session; it never
makes anything listen for a Slack mention. Without the host gateway running,
`@mention`ing the bot produces no reply at all, with no error surfaced
anywhere in the profile itself — confirmed by mentioning a real, fully
configured bot and getting silence, then finding `hermes gateway status`
reporting "not running." The gateway is installed once from the `default`
profile (`hermes gateway install`), not from `kyverno` — a per-profile
`hermes gateway run`/`install` deliberately fails (`exited with code 78`)
once a host gateway exists, to guard against double-binding one bot token
from two pollers.
