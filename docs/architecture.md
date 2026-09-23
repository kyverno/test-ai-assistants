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
`SLACK_MCP_ENABLED_TOOLS=conversations_history` restricts the always-on read
tools, while `conversations_add_message` stays gated by
`SLACK_MCP_ADD_MESSAGE_TOOL=${SLACK_HOME_CHANNEL}` alone — deliberately *not*
also listed in `SLACK_MCP_ENABLED_TOOLS`, because that server's own docs say a
write tool listed there is enabled "without channel restrictions," which would
undo the channel scoping. This layer could not be empirically tested the way
GitHub's was: `korotovsky/slack-mcp-server` validates its Slack token at
process startup and calls `log.Fatal` on failure, before ever reaching the MCP
handshake — so testing it for real needs a valid `SLACK_MCP_XOXB_TOKEN`, which
wasn't available in this pass. Worth doing before install, not blindly
trusted off docs alone. That startup-fatal behavior is itself worth knowing:
an expired or wrong Slack token means the container never starts, not that it
starts with degraded capability.

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
  `pull_request`**. Nothing catches a bad interaction between two merged PRs
  before it's already on `main`.

Because of this, `pr-queue`'s ranking isn't just label/age/milestone sorting — it
has to reason about generated-file conflicts, stacked PRs, and per-PR post-merge
CI risk explicitly, and say so in its output. See `skills/kyverno-context/SKILL.md`
for the codegen/CI reference knowledge and `skills/pr-queue/SKILL.md` for how it's
used.

## Why labels and CODEOWNERS are never hardcoded

`kyverno/kyverno`'s real label set has no "ready for review" / "needs-author-action"
style labels — checked directly, not assumed. Any skill that hardcodes label names
will be wrong the moment it points at a real repo instead of the sandbox one. So
`kyverno-context` resolves labels and CODEOWNERS live (`gh label list`, reading
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
