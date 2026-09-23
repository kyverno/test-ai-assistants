---
name: pr-queue
description: "Ranks a maintainer's PR review queue with cited reasoning."
version: 0.1.0
author: Suhaani Agarwal, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
---

# pr-queue Skill

Fetches and ranks the PRs where the maintainer is a requested reviewer into
an ordered queue with stated reasoning, and answers open-ended follow-up
questions about the queue or any individual PR in it. Relies on
`kyverno-context` for labels/CODEOWNERS and Kyverno's codegen/CI facts —
that skill's knowledge is assumed available, not re-derived here.

## When to Use

- Maintainer asks for their review queue, what to look at next, or what's
  outstanding.
- Maintainer asks about a specific PR, in or out of the current queue.
- Maintainer reports CI broke on `main` and wants to know what's affected.
- Don't use for: taking an action on a PR (label, comment, approve, rebase)
  — that's `pr-actions`. This skill only reads and reasons.

## Prerequisites

- `kyverno-context` loaded this session.
- `mcp-github` tools: `search_pull_requests`, `pull_request_read`,
  `issue_read`, `search_issues`, `list_releases`, `get_latest_release`,
  `list_code_scanning_alerts`,
  `get_code_scanning_alert`, `list_dependabot_alerts`,
  `get_dependabot_alert`, `list_secret_scanning_alerts`,
  `get_secret_scanning_alert`, `actions_list`, `actions_get`,
  `get_job_logs`, `request_copilot_review`.
- `mcp-slack` tools: `conversations_history`.
- Env: `KYVERNO_REPO`, `MAINTAINER_GITHUB_LOGIN`, `SLACK_HOME_CHANNEL`.

## Quick Reference

- `search_pull_requests(query="repo:${KYVERNO_REPO} is:open is:pr review-requested:${MAINTAINER_GITHUB_LOGIN}")`
  — the candidate set. GitHub expands this automatically to PRs where a
  *team* the maintainer belongs to was requested, not only direct requests
  (verified against GitHub's search docs) — no separate CODEOWNERS walk
  needed just to find candidates.
- `pull_request_read(method="get")` — base/head branch names (needed for
  stacked-PR detection below; no other method returns them — confirmed
  against the tool's own schema, and `search_pull_requests` results don't
  carry branch data either).
- `pull_request_read(method="get_files")` — changed files, for
  codegen/package-overlap reasoning.
- `pull_request_read(method="get_reviews" | "get_check_runs" | "get_status" | "get_review_comments" | "get_comments" | "get_diff")`
  — review state, CI state, and PR content for explaining a specific PR.
- `search_pull_requests(query="... milestone:\"<name>\"")` — group by
  milestone; there's no separate milestone-listing tool.
- `list_releases` / `get_latest_release` — real release cadence, as an
  urgency signal alongside milestone due dates.
- `conversations_history(channel_id=SLACK_HOME_CHANNEL)` — priority
  signals mentioning the bot or a specific PR.
- `actions_list(method="list_workflow_runs")` / `actions_get` /
  `get_job_logs` on the repo's push-triggered post-merge workflow — to
  corroborate a *reported* post-merge break with real run data. On demand
  only; never call this speculatively or in a loop (see Pitfalls).

## Procedure: build the ranked queue

1. Fetch the candidate set via `search_pull_requests` as above.
2. Filter to ready-for-review using `kyverno-context`'s live-resolved
   labels plus `draft:false` — never a hardcoded label name.
3. For each candidate: base/head branch (`get`), changed files
   (`get_files`), review/CI state (`get_reviews`, `get_check_runs`), age
   (`created_at`), and milestone (the PR's own field, or a
   milestone-scoped `search_pull_requests`).
4. Cross-reference across the whole candidate set:
   - **Stacked**: PR B's base branch (from step 3's `get`) equals PR A's
     head branch, not the repo default — order B after A regardless of
     other ranking factors.
   - **Generated-file conflict**: two PRs both touch inputs to the same
     `kyverno-context` codegen target — flag explicitly, distinct from an
     ordinary git conflict.
   - **Package overlap**: two PRs touch the same package without
     necessarily git-conflicting — flag as elevated review risk anyway.
   - **Post-merge CI risk**: which packages map to `kyverno-context`'s
     post-merge-only suites, since nothing catches a bad interaction
     before both land.
5. Read `SLACK_HOME_CHANNEL` history for messages naming the bot or a
   specific PR — treat as a ranking signal and cite the message when it
   changes the order.
6. Produce the ordered queue. Every PR's position needs a one-line reason
   — why here, not first or last — stated inline, not as a bare sorted
   list or a separate unreferenced appendix.

Completion criterion: every open candidate PR appears exactly once, in an
order a human could re-derive from the stated reasons alone.

## Answering open-ended questions

A maintainer can ask anything about the queue's state, not only the fixed
list above (see `docs/architecture.md`, "Maintainer questions are
open-ended"): when something about a PR or the repo is unknown, look with
the tools above and cite what was found — never guess or fall back to a
general prior about what a typical Kyverno PR probably looks like. Two
shapes are common enough to call out specifically:

- **"Explain PR #N"** — `pull_request_read` (`get`, `get_diff`,
  `get_reviews`, `get_comments`, `get_review_comments`). Synthesize
  Copilot/CodeRabbit output the same way the old `copilot-review-check`
  pattern did: read their review first, flag only on an actual concerning
  finding, and say plainly if no such review exists yet rather than
  implying one was checked and came back clean. If none exists,
  `request_copilot_review` is available instead of leaving the maintainer
  without that signal. If the PR body references a closing issue ("Closes
  #N", "Fixes #N"), call `issue_read(N, method="get")` — its
  `closed_by_pull_requests` field surfaces whether another PR is also
  configured to close the same issue (a duplicate-effort signal), and its
  own labels/milestone add urgency context the PR itself may not carry.
- **"Is anything else related to this?"** — `search_issues(query="repo:${KYVERNO_REPO} <PR number or topic keywords>")`
  to find issues/discussions that mention the PR or its topic but aren't
  formally linked. Cite what the search actually returned; an empty result
  means "found nothing," not "nothing exists."
- **"CI broke on `main`, what's affected?"** — real input, not something
  monitored for (no polling in v1, see `SOUL.md`). Use
  `actions_list`/`actions_get`/`get_job_logs` on demand to find the actual
  failing run, then cross-reference its failure against file overlap with
  the current queue — name specific PRs and specific overlapping paths,
  not a vague "some PRs might be affected."

## Pitfalls

- Don't assume "ready for review" maps to a specific label name — resolve
  it live via `kyverno-context` every session, same as that skill's own
  rule.
- `review-requested:` already expands team membership for the candidate
  set — don't also run a full CODEOWNERS walk over every open PR just to
  find candidates; save that for explaining *why* one specific PR was
  requested.
- No dedicated milestone tool exists — milestone data comes from search
  query qualifiers and per-PR fields, never a separate listing call.
- Don't poll or loop checking post-merge CI status. Only look when the
  maintainer raises it or asks directly, and even then it's one on-demand
  call, not a watch.
- Security-alert tools (code scanning/Dependabot/secret scanning) enrich
  risk framing for the queue — they're one input among several, not a
  reason to turn this into a full security-review skill.

## Verification

- Ask for the queue twice in a row with no repo state change and confirm
  the order and stated reasons are stable.
- Pick two PRs that touch the same `api/**` path and confirm the queue
  calls out the generated-file conflict explicitly, not just a normal
  ordering difference.
- Ask to explain a PR with no Copilot review yet and confirm the answer
  says so plainly instead of fabricating a review summary.
