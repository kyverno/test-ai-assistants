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
