# Architecture

## The security model

**The LLM never holds a token that can take a privileged action.** This is
enforced in three independent places, not by prompt instructions:

1. **Toolsets.** `config.yaml`'s `custom_toolsets.dependabot-bot-tools` is a
   hand-picked allowlist of read + comment tools from the `mcp-github`
   toolset (see `mcp.json`). It deliberately omits `merge_pull_request`,
   `pull_request_review_write`, `create_or_update_file`, `delete_file`,
   `create_branch`, `create_repository` — every mutating tool the GitHub
   MCP server exposes. `hermes webhook subscribe` has no `--toolsets`
   flag, so no running agent can widen this at runtime; only a human
   editing this file (reviewed like code) can.
2. **The credential itself.** The GitHub MCP server (in `mcp.json`) is
   backed by `KYCTRL_READONLY_GITHUB_TOKEN`, a fine-grained PAT scoped to
   Contents: Read, Pull requests: Read, Issues: Read & Write, Checks: Read
   — no write access to contents or pull requests. Even if a toolset were
   ever misconfigured to include `merge_pull_request`, the call would fail
   at the GitHub API level. Belt and suspenders, deliberately.
3. **Where the actual merge happens.** `.github/workflows/kyctrl-auto-merge.yml`
   is the only place `GITHUB_TOKEN` (Actions' own token, full permissions)
   exists. It triggers on `issue_comment.created`, checks the comment
   contains the literal string `/kyctrl-merge approved` AND was posted by
   the `@kyctrl-bot` App account, then runs `gh pr merge`. Hermes posts
   that comment; Hermes never runs that workflow or holds that token.

## config.yaml vs settings.yaml

Two config files, deliberately different audiences:

| | `config.yaml` | `settings.yaml` |
|---|---|---|
| Controls | routing, toolsets, tool grants | thresholds, toggles, allowlists |
| Changes | who/what can act | how a bot decides |
| Review bar | security review, like code | any maintainer |
| Example | "dependabot-bot may call `add_issue_comment`" | "auto-merge threshold is 70" |

Every deterministic script reads its tunables from `settings.yaml` at
invocation time (no caching, no restart needed) — see
`scripts/dependabot-policy-engine.py`'s `load_settings()`.

## The repo vs. Hermes's runtime data directory

These are deliberately two different directories, learned the hard way in
Phase 0: Hermes's `/opt/data` isn't just "where config lives" — it's where
Hermes writes everything (state databases, per-profile sessions/memory,
caches, cron/kanban state, a whole `lazy-packages/` Python venv, and on
first boot it copies its own ~60 bundled skills in). An early version of
`docker-compose.yml` mounted this repo's root directly as `/opt/data`,
which dumped all of that into the tracked tree. It's fixed now:
`.hermes-data/` (gitignored) is the real `/opt/data`, and `./setup.sh`
one-directionally syncs the tracked config into it before every start.
**Always run `./setup.sh`, never `docker compose up` directly** — that sync
is what keeps the repo clean. See `docker-compose.yml`'s header comment for
the full explanation.

## Why Copilot, not CodeRabbit

The original design used CodeRabbit (free-forever Pro tier for public
repos) as the "something read the diff" signal. This build uses GitHub
Copilot's PR review instead, requested explicitly by
`.github/workflows/copilot-auto-request.yml` on every PR (Copilot doesn't
auto-review without an org-level rule). The check itself —
`skills/copilot-review-check.md` — is written as a shared pattern any
PR-touching bot uses, not something specific to one bot: it's a
downgrade-only gate (can turn an APPROVE into a FLAG, never the reverse),
layered on top of the deterministic checks, never a replacement for them.

## Cross-bot handoffs: trigger comments, not A2A

Hermes's agent-to-agent messaging (A2A) injects tasks into one *live*
gateway session — it's built for one continuously-running agent process,
not for bridging two independent webhook-triggered runs. Every handoff in
this design (e.g. triage-bot → reproduction-bot, from Phase 2 on) goes
through a GitHub comment containing a trigger string
(`/kyctrl-reproduce ...`) that fires a *separate* webhook route bound to
the receiving bot's profile. dependabot-bot doesn't need this in Phase 0
(single bot, no handoff), but the `dependabot-pr` route is written the
same way any future route will be, for consistency.

## Multi-profile gateway constraints (why config.yaml looks the way it does)

- `gateway.multiplex_profiles: true` lets nine profiles share one Hermes
  process on one port.
- Port-binding platforms (`webhook`, `api_server`, ...) are configured
  **only** on the default profile — never inside a `profiles/<name>/config.yaml`.
  Secondary profiles are reached by the `profile:` field on a route (as
  `dependabot-bot` is), or, if ever addressed directly over HTTP, via
  `/p/<profile>/webhooks/<route>`.
- A route's `script` hook receives the webhook payload as JSON on stdin
  and its stdout either replaces the payload (`{...}` JSON), gets merged
  in as `script_output` (plain text), or tells Hermes to ignore the event
  entirely (`[SILENT]`, empty output, or nonzero exit). This is the exact
  mechanism `dependabot-policy-engine.py` uses to inject `kyctrl_verdict`
  into the prompt template and to silently ignore non-Dependabot PRs.

## Known gaps (tracked, not silently ignored)

- **Regression-history memory** (`settings.yaml`'s
  `dependabot_bot.check_regression_history: false`): the original brief
  wanted the policy engine to check "has this exact dependency bump broken
  CI before" using Hermes's memory. Not wired up — it needs Hermes's
  per-profile `state.db` schema understood first. Left as an explicit
  disabled flag rather than a silent no-op.
- **Socket.dev PURL ecosystem mapping** in `get_socket_score()`
  (`npm_and_yarn` → `npm`, `gomod` → `golang`, etc.) was written from docs
  search, not a live API call. Confirm with a real API key before trusting
  a FLAG/APPROVE that hinges on it — see `docs/deployment.md`'s checklist.
- **`kyctrl-bot[bot]` login string** in `kyctrl-auto-merge.yml` assumes the
  GitHub App's slug is exactly `kyctrl-bot`. Confirm once the App exists.
