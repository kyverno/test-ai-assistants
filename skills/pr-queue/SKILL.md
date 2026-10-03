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
- `sequence_prs` (plugin tool, `plugins/kyverno-sequencer/`) — the deterministic candidate
  merge-sequence computation: classification, hard-precedence graph, cycle detection, and a
  weighted CP-SAT rank solve (milestone urgency, age, size, e2e-gate risk, review-readiness).
  See Procedure below for what to pass it and how to treat what it returns.
- `mnemosyne_recall`/`mnemosyne_triple_query` (read) and
  `mnemosyne_remember`/`mnemosyne_triple_add` (write) — see
  `kyverno-context`'s "what this agent remembers, and where" reference for
  the full vocabulary; this skill only calls into it at the specific points
  below.
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
- `sequence_prs(prs=[...], precedence_hints=[...], repo_default_branch=..., gate_open=...)` —
  pass every candidate's changed files/labels/branches/milestone-alignment/review-readiness
  (all already fetched per Procedure step 2), plus any interface/dependency-usage edges you've
  derived from `search_code` as `precedence_hints` (it can't derive those itself — see the
  tool's own schema description). Returns a candidate `sequence`, any `cycles` (unresolvable —
  hand to the maintainer, don't pick an order), `unresolved` pairs, and which solver ran.
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

1. Fetch the candidate set: human and Dependabot PRs carrying
   `label:ready-for-review`, plus Dependabot PRs carrying `label:needs-review`
   — all of them enter the same graph and the same final sequence. A
   `needs-review` entry carries its diagnosed blocker (step 5 below) with it
   into its sequence position; it is never pulled into a side list.
   **This set can be 100+ PRs on a real repo** — `total_count` is accurate,
   not inflated; don't fetch it all. Default to a manageable slice unless
   asked for everything:
   - `perPage` 10-15 per call.
   - Add any filter the maintainer named (milestone, `release-critical`/
     `release-high`, a label) as its own query qualifier, not a
     post-filter over the full set.
   - State the slice size vs. the total (e.g. "top 12 of 146") — never
     present a partial sequence as if it were the whole queue.
2. For every candidate in one turn, emit the changed-files fetch
   (`get_files`) concurrently rather than sequentially. Also fetch
   base/head branch (`get`), age (`created_at`), milestone, and a
   `get_reviews`/`get_review_comments` pass for review-readiness (CodeRabbit
   approval + unresolved-thread count) for each. For a Dependabot candidate,
   `get_files` is almost always `go.mod` / `go.sum` (+ any vendored/generated
   files this repo's build produces); note the bumped module path from the
   diff — pass it as `dependency_bumps` so `sequence_prs` can treat a
   `github.com/kyverno/api` bump as a generated-file-input touch even with
   no `api/**` path in `changed_files`. Also resolve each candidate's
   `milestone_alignment` ("direct" / "referenced" / "none") here — from its
   closing issue (`issue_read`, see "Explain PR #N" below) and that issue's
   milestone; `sequence_prs` uses it as a soft-priority weight, not a
   tie-break. A Dependabot PR has no closing issue: pass `"none"`.
3. Before calling the tool, work out anything it can't derive from file
   paths alone and pass it as `precedence_hints`:
   - **Interface conflict**: a shared interface-tier file (per
     `kyverno-context`'s vocabulary) where the diffs make the
     definer-before-implementer direction unambiguous — a
     `{before, after, reason}` hint. Direction not derivable: don't guess
     — leave it out and separately flag the pair for a human.
   - **Dependency-usage edge (Dependabot, non-codegen dependencies)**: for
     a bumped module that isn't itself a generated-file input,
     `search_code` its import path within `KYVERNO_REPO`. Any other open
     candidate whose own changed files import it becomes a
     `{before: candidate, after: dependabot_pr}` hint — the bump lands
     after that PR, so its review isn't done against a dependency surface
     that just moved.
   Stacked-branch edges and generated-file input-before-output edges don't
   need a hint — `sequence_prs` derives both mechanically from
   `base_branch`/`head_branch`/`changed_files`/`dependency_bumps`.
4. Call `sequence_prs` with every candidate's fetched metadata (step 2),
   the `precedence_hints` from step 3, `repo_default_branch`, and whether
   an `e2e-failure` issue is currently open for the target branch
   (`gate_open`). Treat the result as a **candidate**, not a verdict:
   - Any `cycles` entry means the tool found a genuine contradiction — hand
     those PRs to the maintainer named explicitly, don't pick an order.
   - Any `unresolved` entry (e.g. two PRs both touching a generated-file
     input with no derivable order between them) gets the same treatment.
   - Package overlap (same package, no file-level edge) isn't something the
     tool flags as risk on its own — note it yourself if you notice it
     while reading the candidates' changed files; it's an elevated-review
     signal, not a sequencing constraint.
   - Post-merge CI risk: cross-check the candidate order's `risk`/`warnings`
     fields against `kyverno-context`'s post-merge-only suites and, per
     candidate's touched packages, `mnemosyne_triple_query` for a
     `caused_e2e_failure` predicate — an actual historical incident on that
     combination is a stronger, more specific note than the tool's generic
     gate-risk flag alone; cite the incident (PR#, date) when one exists,
     and say plainly when the query returns nothing.
   - If the tool's candidate order doesn't match something you know from
     Slack (step 7 below) or a maintainer instruction earlier in the
     conversation, say so explicitly and explain the override — never
     silently repeat the candidate as-is *or* silently reorder it.
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
6. Read `SLACK_HOME_CHANNEL` history for messages naming the bot or a
   specific PR — treat as a ranking signal and cite the message when it
   changes the order (per step 4's override rule above).
7. Produce the one ordered sequence from `sequence_prs`'s candidate,
   step 5's diagnosis, and step 6's Slack check. Every position — human or
   Dependabot, `ready-for-review` or `needs-review` — needs a one-line,
   citable reason; a `needs-review` entry's reason is its diagnosed cause
   from step 5, not just the label name; a position you've overridden from
   the tool's candidate needs its override reason stated, not silently
   substituted.

Completion criterion: every candidate from step 1 appears exactly once, in
the position `sequence_prs` plus steps 5-6's overrides actually puts it,
and a human could re-derive the whole order from the stated reasons alone.
This phase's sequencing quality doesn't depend on anything actually
merging — the precedence graph and weighted candidate order are the whole
value; who mechanically executes a merge afterward is a separate concern.

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
   bare verdict with no citation. Before drafting, `mnemosyne_recall` for
   durable notes on this PR's author (e.g. "needs multiple rounds on
   generated-file changes") to calibrate tone/thoroughness — a real,
   cited pattern, not a guess about the contributor.

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
  to find currently-open issues/discussions that mention the PR or its
  topic but aren't formally linked, plus `mnemosyne_recall` for closed,
  rejected, or deferred PRs on the same topic with a known reason —
  extends the check past what's currently open into history with *why*.
  Cite what was actually returned from each; an empty result means "found
  nothing," not "nothing exists."
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
  confirm the order and stated reasons are stable (`sequence_prs` is
  deterministic for identical input).
- Pick two PRs that touch the same `api/**` path and confirm the sequence
  calls out the generated-file conflict explicitly, with an input-before-
  output order or an explicit human flag, not just a normal ordering
  difference.
- Ask for the sequence when two otherwise-comparable candidates differ only
  in review-readiness (one CodeRabbit-approved with no unresolved threads,
  one not) and confirm the ready one ranks earlier with that reason stated.
- Confirm the presented sequence visibly checks `sequence_prs`'s candidate
  against Slack/Dependabot context — agreeing, disagreeing, or overriding
  with a stated reason — rather than repeating the tool's output verbatim.
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
- Flag a PR touching a package-pair with a known `caused_e2e_failure`
  triple and confirm the merge sequence cites the specific past incident,
  not just the generic post-merge-suite warning.
- Ask "is anything else related to this" about a topic with a real
  closed/rejected PR history and confirm `mnemosyne_recall` surfaces it
  with the reason, not just currently-open search results.
