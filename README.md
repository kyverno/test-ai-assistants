# kyverno-assistant

An on-demand PR review queue assistant for a Kyverno maintainer, built as a
[Hermes profile distribution](https://hermes-agent.nousresearch.com/docs/user-guide/profile-distributions):
`distribution.yaml` + `SOUL.md` + `config.yaml` (which declares the GitHub and
Slack MCP servers directly — no separate `mcp.json`) + `skills/` + `hooks/`.
One maintainer installs it, fills in their own credentials, and talks to it on
Slack or via `kyverno chat` — no server to run, no webhook receiver.

**Status:** works today — install it and use it. Not yet validated across
multiple real maintainers' workflows (`docs/deployment.md`'s validation
plan), which is the bar for graduating to a dedicated
`kyverno/kyverno-assistant` repo.

## Setup, from scratch

### 1. Prerequisites

- [Docker](https://docs.docker.com/get-docker/), running — the GitHub and
  Slack tools each run as their own container, no separate install.
- The [Hermes CLI](https://hermes-agent.nousresearch.com) on your `PATH`.
- A model provider — either one:
  - an Anthropic API key, or
  - a GitHub Copilot seat with Claude Sonnet enabled, plus a fine-grained PAT
    owned by your **personal** account (not an org) with the Account
    permission **Copilot Requests**. This is a separate token from the one
    in step 3.

### 2. Clone this repo

```bash
git clone https://github.com/kyverno/test-ai-assistants.git
cd test-ai-assistants
```

(This assistant is prototyped in this sandbox repo rather than a dedicated
one for now — see the Status note above. Install from the local checkout,
as below, not from a git URL.)

### 3. Get a GitHub token

A fine-grained personal access token, scoped to the repo you'll point this
at (`kyverno/kyverno` for real use, or `kyverno/test-ai-assistants` to try
the sandbox scenarios first): Contents Read, Pull requests Read & Write,
Issues Read & Write, Checks Read, Code scanning alerts Read, Dependabot
alerts Read, Secret scanning alerts Read, org Members Read. No Contents
Write and no merge/admin scope — see `docs/architecture.md` for the full
reasoning.

### 4. Set up Slack (optional — skip for CLI-only use)

Two separate things share one Slack app here: the **bot** you `@mention` or
DM to talk to the assistant conversationally, and a **tool** the assistant
calls on its own to read the maintainers channel's history and post into
it (e.g. the merge sequence, or a reply in a PTAL thread). Both need to live
in the **same Slack workspace** as each other and as the maintainers
channel you want it reading/posting to — a bot installed in one workspace
can't see or act on a channel in a different one.

1. [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** →
   **From scratch**. Name it, pick your workspace.
2. **OAuth & Permissions** → add Bot Token Scopes: `chat:write`,
   `channels:history`, `channels:read`, `app_mentions:read`, `groups:read`,
   `mpim:read`, `im:read`. (The last three are needed even though this
   assistant only reads one public channel — the Slack tool fetches every
   channel type in one call at startup and needs a scope for each.)
3. **Socket Mode** → turn it on → generate an App-Level Token with the
   `connections:write` scope. Save it.
4. **Event Subscriptions** → turn it on → subscribe to bot events:
   `app_mention`, `message.channels`.
5. **Install App** (to your workspace) → copy the **Bot User OAuth Token**.
6. Invite the bot to your maintainers channel (`/invite @<bot-name>`), then
   grab that channel's ID and your own Slack member ID (both from the
   **...** / channel-details menus in Slack).
7. If you add or change scopes after installing, click **reinstall your
   app** on the OAuth & Permissions page — scope changes need that to take
   effect.

### 5. Install everything else

```bash
./scripts/install.sh
```

One script, re-run as many times as you need — it detects what's already
done and only does what's left:

- First run installs the profile, then stops and tells you exactly which
  credentials to fill in at `~/.hermes/profiles/kyverno/.env` (copied
  there from `.env.EXAMPLE`): your GitHub token, `MAINTAINER_GITHUB_LOGIN`,
  `KYVERNO_REPO`, one model provider (`ANTHROPIC_API_KEY` or
  `COPILOT_GITHUB_TOKEN`), and — if you did step 4 — the four
  Slack values. Full detail on each var: `docs/deployment.md`.
- Fill those in, then run `./scripts/install.sh` again. It installs the
  messaging gateway (only if you set up Slack), then sanity-checks the
  toolset — GitHub/Slack MCP servers reachable, hooks approved — and
  prints ✓/✗ per check.

`hermes profile install` itself has no non-interactive way to accept
credentials — pasting real values into `.env` once is the one manual step
nothing here can skip.

### 6. Run it

```bash
kyverno chat
```

or mention the bot in the Slack channel you invited it to.

### 7. Turn on the review digest (optional)

A scheduled job ships with the profile — a weekday-morning merge-sequence
digest posted to your Slack channel — but arrives paused, since a
distribution shouldn't post to your Slack on a schedule without you looking
first:

```bash
hermes cron list      # see it: "kyverno-review-digest", paused
hermes cron resume kyverno-review-digest
```

Want a different time or channel? `hermes cron edit kyverno-review-digest`.

`docs/capabilities.md` has a full tour with example prompts.
`docs/test-scenarios.md` has a ready-made set of test PRs/issues on
`kyverno/test-ai-assistants` if you want to try it before pointing it at
`kyverno/kyverno`.

## What it does

- Fetches every open PR matching a stated focus (milestone/author/area/label — never a
  hardcoded label name, `kyverno-context` resolves the real set live) in one batched call
  (`kyverno-fetch`), human and Dependabot PRs together.
- Builds a dependency graph and layers it into tiers — stacked PRs, generated-file
  conflicts, explicit body references, closing-issue conflicts (`kyverno-sequencer`) —
  then orders within each tier by a precedence ladder (closing-issue severity, milestone
  proximity, CodeRabbit approval + unresolved threads, author association, size) and names
  the reason for every position (`pr-queue`).
- Checks Slack and GitHub Discussions for context on a PR or the queue as a whole, and the
  live e2e-gate status per target branch — independent of `ready-for-review`, never
  conflated with it.
- Asked about Dependabot specifically, reviews every open Dependabot PR and says which to
  merge now, fix first, review yourself, wait on, or close — with real call sites, release
  notes, and Copilot's findings.
- Explains any PR on request — short by default, deeper (review threads, risk, a suggested
  action, Slack/Discussions context) on request — and answers open-ended questions about the
  repo or queue by looking things up rather than guessing (`docs/architecture.md`,
  "Maintainer questions are open-ended").
- Labels, comments, requests changes, approves, and catches a PR's branch up with its base
  (`pr-actions`) using the maintainer's own credentials — a GitHub-API merge-update, not a
  git rebase, even when asked to "rebase"; see that skill for why.
- Reads and answers GitHub Discussions, drafting a reply and waiting for confirmation before
  posting (`discussions`).

**Cannot merge** — no merge tool exists in its toolset, enforced in three
independent layers. See `docs/architecture.md`.

Remembers durably across sessions — current focus and working style, plus
an accumulating store of past incidents, rejected PRs, and contributor
patterns, retrieved automatically where relevant (e.g. flagging post-merge
risk with real cited history, not just "no data"). See
`docs/capabilities.md`'s "Remembering things across sessions".

`docs/workflow.md` is the full target workflow (issue triage, a dashboard, session
open/close) and its own "Build plan" section tracks what's built against what's still ahead.

## Layout

- `distribution.yaml` — install manifest: name, version, required env vars.
- `scripts/install.sh` — idempotent installer: profile install, credential
  check, gateway install, AGENTS.md cache seeding, toolset sanity checks.
  Re-run after each step it asks for (see Setup step 5).
- `SOUL.md` — the agent's identity and boundaries.
- `config.yaml` — model default, the GitHub/Slack MCP server declarations
  (`mcp_servers:`), and the hand-picked tool allowlist. Security-critical,
  hand-edited only.
- `hooks/block-dangerous-tools.sh` — a `pre_tool_call` backstop that rejects
  any merge/delete-repo/force-push-shaped tool call.
- `hooks/block-mnemosyne-triples.sh` — a `pre_tool_call` backstop that
  restricts the memory plugin's `triple_add` tool to the exact set of facts
  this distribution actually writes.
- `plugins/kyverno-fetch/` — a bundled Hermes plugin registering
  `fetch_pr_candidates`/`fetch_file_diff_overlap`: one batched call over
  GitHub's GraphQL/REST APIs in place of a search-plus-per-PR-read sequence.
  See `docs/architecture.md`.
- `plugins/kyverno-sequencer/` — a bundled Hermes plugin registering
  `sequence_prs`: a hard-dependency graph (stacked branches, generated-file
  ordering, explicit references, closing-issue conflicts), cycle detection,
  and topological layering into tiers — `pr-queue` orders within each tier
  itself. See `docs/architecture.md`.
- `cron/jobs.json` — scheduled jobs the distribution ships: a weekday
  review digest posted to Slack, and two silent background jobs that keep
  memory current (`kyverno-memory-sweep`, `kyverno-memory-consolidate`).
  Installed paused; the maintainer reviews and resumes each one (see Setup
  step 7).
- `skills/kyverno-context/` — dynamically-resolved labels/CODEOWNERS
  (never hardcoded — re-resolved live every session) plus Kyverno's real
  codegen fan-out, pre-/post-merge CI split, and e2e-gate mechanics.
- `skills/pr-queue/` — fetch, tier, and explain the review queue: the
  precedence ladder, Slack/Discussions context, gate check, and per-PR
  review briefs — tools + fixed facts + "look, don't guess," not a fixed
  script per question (see `docs/architecture.md`).
- `skills/pr-actions/` — label/comment/request-changes/approve/branch-update,
  all via the maintainer's own token; explicit about what it can't do
  (merge, true rebase, post-merge CI monitoring) and why.
- `skills/discussions/` — reads and answers GitHub Discussions; drafts a
  reply and waits for confirmation before posting, since a discussion
  answer is visible to the whole community, not just the maintainer.
- `docs/architecture.md` / `docs/deployment.md` — design and install runbook.
- `docs/capabilities.md` — a tour of what it can do, with example prompts.
- `docs/workflow.md` — the target maintainer workflow (PR work, issue work,
  session open/close, the dashboard) and, in its own "Build plan" section,
  the current phased plan for what's not built yet.
- `docs/test-scenarios.md` — the fake PR/issue/CODEOWNERS environment built
  on this repo for exercising the skills against realistic-shaped data.
- `docs/testing-guide.md` — prompts exercising every capability above,
  grounded in real counts on `kyverno/kyverno`.
- `docs/archive/` — operational notes from the abandoned `kyctrl` design
  this repo previously held (kept for reference, not part of this project).
