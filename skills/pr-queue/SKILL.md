---
name: pr-queue
description: "Merge-sequence recommendations and per-PR review briefs, cited."
version: 0.1.0
author: Suhaani Agarwal, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
---

# pr-queue Skill

Fetches the readiness-gated candidate set and builds an ordered
merge-sequence recommendation with cited reasoning, and answers open-ended
follow-up questions about the queue or any individual PR in it. Relies on
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
  `issue_read`, `search_issues`, `search_code`, `list_releases`,
  `get_latest_release`, `list_code_scanning_alerts`,
  `get_code_scanning_alert`, `list_dependabot_alerts`,
  `get_dependabot_alert`, `list_secret_scanning_alerts`,
  `get_secret_scanning_alert`, `actions_list`, `actions_get`,
  `get_job_logs`, `request_copilot_review`.
- `mcp-slack` tools: `conversations_history`, `conversations_add_message`.
- Env: `KYVERNO_REPO`, `MAINTAINER_GITHUB_LOGIN`, `SLACK_HOME_CHANNEL`.

## Quick Reference

- `search_pull_requests(query="repo:${KYVERNO_REPO} is:open is:pr draft:false label:ready-for-review")`
  and the same query with `label:needs-review` — together, the full
  candidate set for the merge sequence. `pr-readiness-check.yaml`/
  `dependabot-merge-triage.yaml` already gate CI/DCO/conflicts/review-
  threads/Copilot-approval before applying `ready-for-review`; a
  `needs-review` entry (always a Dependabot PR) takes its diagnosed
  blocker with it into the same sequence rather than a side list (see
  Procedure below).
- `pull_request_read(method="get")` — base/head branch names (needed for
  stacked-PR detection below; no other method returns them — confirmed
  against the tool's own schema, and `search_pull_requests` results don't
  carry branch data either).
- `pull_request_read(method="get_files")` — changed files, for
  codegen/interface/package-overlap reasoning. Fetch this for every
  candidate in one model turn (Hermes genuinely executes concurrent tool
  calls emitted together) rather than one PR at a time.
- `pull_request_read(method="get_reviews" | "get_check_runs" | "get_status" | "get_review_comments" | "get_comments" | "get_diff")`
  — review state, CI state, and PR content for explaining a specific PR.
  `get_review_comments` returns each thread's `is_resolved` directly
  (confirmed against the tool's real schema — resolved-state *is* exposed,
  not just raw comments) — use it over `get_comments` when the question is
  about outstanding review threads specifically.
- `search_pull_requests(query="... milestone:\"<name>\"")` — group by
  milestone; there's no separate milestone-listing tool.
- `list_releases` / `get_latest_release` — real release cadence, as an
  urgency signal alongside milestone due dates on the main sequence; also
  the source for a bumped dependency's own release notes when explaining a
  `major-bump` PR (call against that dependency's own `owner`/`repo`,
  derived from its Go module path, not `KYVERNO_REPO`).
- `search_code(query="<bumped import path> repo:${KYVERNO_REPO}")` — real
  call sites of a bumped dependency within `KYVERNO_REPO`, to name the
  actual blast radius of a `major-bump` PR instead of a generic warning.
- `conversations_history(channel_id=SLACK_HOME_CHANNEL, limit="<window>")`
  — priority signals mentioning the bot or a specific PR; no query param,
  see "Review brief" step 6 for why and how to search it anyway.
- `conversations_add_message(channel_id=SLACK_HOME_CHANNEL, thread_ts=..., ...)`
  — post the queue into the channel when asked to ("share this with the
  channel", "post the queue"), or reply in a thread (`thread_ts` set to the
  parent message's timestamp) when following up on a specific PTAL thread.
  Hermes' own Slack platform already handles replying in the conversation
  the maintainer is chatting in — this tool is only for the distinct case
  of posting into `SLACK_HOME_CHANNEL` on request, including when the
  maintainer asked via CLI, not Slack.
- `actions_list(method="list_workflow_runs")` / `actions_get` /
  `get_job_logs` on the repo's push-triggered post-merge workflow — to
  corroborate a *reported* post-merge break with real run data. On demand
  only; never call this speculatively or in a loop (see Pitfalls).

## Procedure: build the merge-sequence recommendation

1. Fetch the full candidate set in one pass: human and Dependabot PRs
   carrying `label:ready-for-review`, plus Dependabot PRs carrying
   `label:needs-review` — all of them enter the same graph and the same
   final sequence. A `needs-review` entry carries its diagnosed blocker
   (step 5 below) with it into its sequence position; it is never pulled
   into a side list.
2. For every candidate in one turn, emit the changed-files fetch
   (`get_files`) concurrently rather than sequentially. Also fetch
   base/head branch (`get`), age (`created_at`), and milestone for each.
   For a Dependabot candidate, `get_files` is almost always `go.mod` /
   `go.sum` (+ any vendored/generated files this repo's build produces);
   note the bumped module path from the diff for step 4's usage edge.
3. Classify every changed file per `kyverno-context`'s risk vocabulary
   (generated / interface / test-only / unclassified).
4. Build the file-overlap conflict graph: an edge between any two
   candidates sharing a changed or generated-output path. Cross-reference
   the whole candidate set on top of it:
   - **Stacked**: PR B's base branch equals PR A's head branch, not the
     repo default — a hard edge, B after A, independent of the graph.
   - **Generated-file conflict**: an edge where the shared path is a
     generated-file *input* — order input-before-output when one side is
     literally the codegen run; otherwise this pair has no derivable
     order — flag it for a human rather than picking one. A Dependabot PR
     bumping `github.com/kyverno/api` (or an equivalent code-generating
     dependency) counts as touching a generated-file input by
     `kyverno-context`'s fan-out map — check it against the same generated
     *output* paths (CRDs/clientset/CLI copies/chart templates) any other
     candidate touches, not just against literal `go.mod` overlap.
   - **Interface conflict**: an edge on an interface-tier file — order
     definer-before-implementer when the diffs make the direction
     unambiguous; flag a cycle for a human otherwise.
   - **Dependency-usage edge (Dependabot, non-codegen dependencies)**:
     for a bumped module that isn't itself a generated-file input,
     `search_code` its import path within `KYVERNO_REPO`. Any other open
     candidate whose own changed files import it gets a hard edge — the
     bump lands after that PR, so the PR's own review isn't done against a
     dependency surface that just moved. No such candidate: fall through
     to milestone-alignment/age like any unconstrained entry.
   - **Package overlap** (no file-level edge, same package): flag as
     elevated review risk, not a sequencing constraint.
   - **Post-merge CI risk**: which packages map to `kyverno-context`'s
     post-merge-only suites — a per-PR risk note, not a sequencing edge.
     Check whether an `e2e-failure` issue is already open for the target
     branch first; if so, say the whole queue is currently gated, don't
     bury that inside one PR's note.
5. **Diagnose every `needs-review` entry** rather than reporting the bare
   label: read `get_reviews` for Copilot's verdict body, `get_check_runs`/
   `get_status` for failing checks, and `get`'s mergeable-state field for a
   conflict — name the actual cause (e.g. "Copilot flagged the changelog
   note as missing," not "not approved yet"). For a `major-bump` entry,
   also pull the bumped module's own `list_releases`/`get_latest_release`
   (against that module's own `owner`/`repo`, from its import path) for
   what changed between versions, and the dependency-usage edge's
   `search_code` results for which of this repo's call sites the bump
   actually touches — give the maintainer the real blast radius, not a
   generic "this is a major bump" warning. A `github.com/kyverno/api` bump
   specifically needs two extra checks beyond that, per `kyverno-context`'s
   codegen fan-out: (a) `search_code` for the `policies.kyverno.io` type
   names/import aliases actually used in hand-written `pkg/**` code (not
   just a raw import-path match — a breaking field rename there is the
   real risk, distinct from generated code); (b) whether this PR's own
   diff already includes the matching regenerated outputs (`config/crds/
   policies.kyverno.io/**`, the `policies.kyverno.io` slice of `pkg/client/
   **`, the CLI's CRD copies, the chart's CRD templates) — a bare `go.mod`/
   `go.sum`-only diff means every one of those is now stale relative to the
   new upstream types, which is a distinct, citable finding from "major
   bump, check for breaking changes" and should be named explicitly. When
   the diagnosed cause has an obvious, scoped fix (a changelog line, a
   renamed-API call site named explicitly in Copilot's review, a lockfile
   regen, running the codegen targets that produce the stale outputs just
   named), describe the fix and ask the maintainer whether to apply it —
   see `pr-actions` for what happens next.
6. Topologically sort the graph (stacked/generated-input/interface/
   dependency-usage edges as hard ordering constraints). Any cycle: don't
   invent an order — name the PRs in the cycle and hand it to the
   maintainer. Within each unconstrained tier, reorder by
   milestone-alignment (closes the milestone issue directly > closes an
   issue the milestone issue itself references > age as tiebreaker) — this
   needs each candidate's closing issue (`issue_read`, see "Explain PR #N"
   below) and that issue's milestone. A Dependabot PR has no closing issue;
   its tier position comes from the dependency-usage edge or age alone.
7. Read `SLACK_HOME_CHANNEL` history for messages naming the bot or a
   specific PR — treat as a ranking signal and cite the message when it
   changes the order.
8. Produce the one ordered sequence. Every position — human or
   Dependabot, `ready-for-review` or `needs-review` — needs a one-line,
   citable reason; a `needs-review` entry's reason is its diagnosed cause
   from step 5, not just the label name.

Completion criterion: every candidate from step 1 appears exactly once, in
the position its file-overlap/dependency-usage/milestone reasoning actually
puts it, and a human could re-derive the whole order from the stated
reasons alone. This phase's sequencing quality doesn't depend on anything
actually merging — the topological sort is the whole value; who
mechanically executes a merge afterward is a separate concern.

## Review brief: explain PR #N

Every question about a specific PR resolves live, from these tools, every
time — no cache, no carrying an answer from earlier in the conversation
into a later question about the same PR (a review, a comment, or a check
can land in between). The short form (default) is: what it changes, why,
and existing review-tool output. The long form (asked for specifically, or
whenever a signal below is actually concerning) adds review-thread state,
risk, a suggested action, and Slack context.

**Short form:**

1. What it changes: plain-language purpose from `get_diff` and `get_files`,
   not a diff dump.
2. Why: the issue it closes, via the PR body's "Closes/Fixes #N" plus
   `issue_read(N, method="get")` — its `closed_by_pull_requests` field
   surfaces whether another PR is also configured to close the same issue
   (a duplicate-effort signal), and its own labels/milestone add urgency
   context the PR itself may not carry.
3. Existing review output: `get_reviews` for Copilot's and CodeRabbit's
   verdicts, synthesized per the real division of labor (CodeRabbit:
   security/lint/tests/CI/codegen freshness; Copilot: logic/architecture/
   cross-file impact — see `kyverno-context`). Read their review first,
   flag only on an actual concerning finding, and say plainly if neither
   has reviewed it yet rather than implying a clean check happened.
   `request_copilot_review` is available if one's missing.

**Long form adds:**

4. Review-thread state: `get_review_comments` for each thread's
   `is_resolved` plus its last comment's author — an unresolved thread
   whose last comment isn't the PR author's is a real open item, distinct
   from "review comments exist." Name which threads, not just a count.
5. Risk: same file-risk classification and post-merge/`e2e-gate` check as
   Procedure steps 3-4 above, applied to this one PR.
6. Slack context: `conversations_history(channel_id=SLACK_HOME_CHANNEL, limit="7d")`
   (widen the window if asked to check further back — Slack's own
   `search.messages` API doesn't work with a bot token at all, so there is
   no server-side search here; `conversations_history` takes no query
   parameter either, only a time/count `limit` — this is a bounded scan and
   a client-side text-match against the PR's number/title/URL, not a
   search). Say plainly that an empty result means "not mentioned in the
   window checked," not "never discussed" — and name the window checked.
   If a PTAL-shaped thread turns up, draft a reply and show it to the
   maintainer; only on their confirmation, post it directly with
   `conversations_add_message` (`thread_ts` set to that message's own
   timestamp) — the same tool and confirm-then-post pattern already used
   for posting the queue itself, not a `pr-actions` action (that skill has
   no Slack tools; its domain is GitHub actions on the maintainer's own
   `GITHUB_TOKEN`). Cannot check whether someone already replied in that
   thread first (`conversations_replies` isn't granted here) — say so
   plainly rather than drafting as if the thread were still untouched.
7. Suggested action: one of approve / request changes / wait on CI / needs
   the author to resolve threads / proceed but flagged as high post-merge
   risk — derived from steps 3-5 above, stated with the reason, never a
   bare verdict with no citation.

Completion criterion: every claim in the brief traces to a specific tool
call made in this same turn, and the maintainer could tell from the answer
alone which of the two forms they got.

## Answering open-ended questions

A maintainer can ask anything about the queue's state, not only the fixed
list above (see `docs/architecture.md`, "Maintainer questions are
open-ended"): when something about a PR or the repo is unknown, look with
the tools above and cite what was found — never guess or fall back to a
general prior about what a typical Kyverno PR probably looks like. Two
shapes are common enough to call out specifically:

- **"Explain PR #N"** — see "Review brief" below for the full shape; default
  to the short form, go deeper only when asked.
- **"Is anything else related to this?"** — `search_issues(query="<PR number or topic keywords, as plain language>", owner=..., repo=...)`
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
- The readiness workflows already gate CI/DCO/conflicts/threads before
  applying `ready-for-review` — don't recompute that gating client-side by
  walking CODEOWNERS or checks yourself; use the label as the filter.
- `search_issues` takes a natural-language query — use its own
  `owner`/`repo` parameters for repo scoping, and filter on the returned
  `milestone` field client-side for a milestone-scoped issue search.
  `search_pull_requests` is the tool for qualifier-syntax queries like
  `milestone:"..."`. No dedicated milestone-listing tool exists either
  way.
- Don't poll or loop checking post-merge CI status. Only look when the
  maintainer raises it or asks directly, and even then it's one on-demand
  call, not a watch.
- Security-alert tools (code scanning/Dependabot/secret scanning) enrich
  risk framing for the queue — they're one input among several, not a
  reason to turn this into a full security-review skill.
- Never report a Dependabot `needs-review` entry with just the label name
  — diagnose the actual cause (Copilot's verdict, failing checks, or a
  conflict) every time, per step 5 of the Procedure.

## Verification

- Ask for the merge sequence twice in a row with no repo state change and
  confirm the order and stated reasons are stable.
- Pick two PRs that touch the same `api/**` path and confirm the sequence
  calls out the generated-file conflict explicitly, with an input-before-
  output order or an explicit human flag, not just a normal ordering
  difference.
- Confirm a Dependabot `needs-review` PR's position in the sequence comes
  with a diagnosed cause (Copilot's verdict, a failing check, or a
  conflict), not just the bare label name.
- For a `major-bump` PR, confirm the explanation names real call sites in
  `KYVERNO_REPO` (from `search_code`) and the dependency's own release
  notes, not a generic "this is a major bump, be careful" warning.
- Ask to explain a PR with no Copilot review yet and confirm the answer
  says so plainly instead of fabricating a review summary.
- Ask a milestone-scoped question about issues (not PRs) and confirm
  `search_issues` is called with a plain-language query plus `owner`/`repo`
  parameters, with milestone filtering happening on the returned data.
- Ask to explain a PR plainly and confirm the short form only — no
  review-thread/risk/Slack section unless asked or something's wrong.
- Ask whether a PR was discussed in Slack and confirm the answer names the
  time window checked, not a bare yes/no.
