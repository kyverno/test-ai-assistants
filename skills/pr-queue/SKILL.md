---
name: pr-queue
description: "Merge-sequence recommendations and per-PR review briefs, cited and linked."
version: 0.3.0
author: Suhaani Agarwal, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
---

# pr-queue Skill

Builds an ordered merge-sequence recommendation and answers open-ended questions about
the queue or any individual PR. Relies on `kyverno-context` for labels/CODEOWNERS/
milestone/fixed facts — assumed loaded, not re-derived here.

## When to Use

- Maintainer asks for their review queue, what's outstanding, or about a specific PR.
- Maintainer reports CI broke on `main` and wants to know what's affected.
- Not for: taking an action (label, comment, approve, rebase) — that's `pr-actions`.

## Prerequisites

- `kyverno-context` loaded this session.
- `fetch_pr_candidates` (plugin tool, `plugins/kyverno-fetch/`) — one call fetches
  every candidate's full metadata.
- `sequence_prs` (plugin tool, `plugins/kyverno-sequencer/`) — builds the hard-
  dependency graph and layers it into tiers.
- `mcp-github`: `search_issues`, `issue_read`, `search_code`, `list_releases`,
  `get_latest_release`, `list_code_scanning_alerts`, `get_code_scanning_alert`,
  `list_dependabot_alerts`, `get_dependabot_alert`, `list_secret_scanning_alerts`,
  `get_secret_scanning_alert`, `actions_list`, `actions_get`, `get_job_logs`,
  `request_copilot_review`, `pull_request_read` (review-brief deep dives only —
  `fetch_pr_candidates` already covers the main queue build).
- `mcp-slack`: `conversations_history`, `conversations_add_message`.
- `mnemosyne_recall`/`_triple_query` (read), `mnemosyne_remember`/`_triple_add`
  (write) — see `kyverno-context`'s memory reference.
- Env: `KYVERNO_REPO`, `MAINTAINER_GITHUB_LOGIN`, `SLACK_HOME_CHANNEL`.

## Procedure: build the merge-sequence recommendation

**Step 0 — establish a focus before fetching.** If the request already names one,
skip to Step 1. Otherwise ask: a milestone, an author, an area (package/folder), or
`workflow-approval-required` PRs instead of the review queue. Never default to
oldest-first or "all PRs." Exception: `cron/jobs.json`'s `kyverno-review-digest` has
no one to ask — use a fixed fallback (highest-urgency closing-issue label, then
`coderabbit_approved` + zero unresolved threads, then most-recently-updated) and
label it as the digest default, not the general rule.

1. **Fetch**: `fetch_pr_candidates(repo=KYVERNO_REPO, search_query="label:ready-for-review")`
   plus the same call with `label:needs-review` — or one call with
   `"label:ready-for-review,needs-review"` if the tool's search syntax supports an
   OR (check its schema). Add whatever Step 0 established as its own qualifier
   (`milestone:"..."`, `author:...`) rather than post-filtering. An area/package
   focus is a client-side filter on the returned `changed_files` instead, since
   GitHub search has no path qualifier. State the slice size vs. `total_count`
   whenever the set is narrowed. If Step 0 picked `workflow-approval-required`,
   fetch that separately and present it as its own short list (Output format below)
   — it never goes into `sequence_prs`.
2. **Precedence**: nothing to prepare — `sequence_prs` derives all four hard-edge
   types (stacked, generated-file, explicit body reference, closing-issue conflict)
   itself from the fetched `body`/`changed_files`/`closing_issues`/`dependency_bumps`.
3. **Gate check**: `search_issues(query="is:open label:e2e-failure", owner=..., repo=...)`,
   every time, cited — never assert "no gate open" without this call. Pass each open
   issue's branch marker (or `null` if it has none) as `blocking_issue_branches`.
4. **Call `sequence_prs`** with every candidate's `number`/`changed_files`/`labels`/
   `base_branch`/`head_branch`/`body`/`closing_issues` (numbers only)/`dependency_bumps`,
   `repo_default_branch`, and `blocking_issue_branches`. It returns `tiers` (each PR
   tagged with `hard_constraints`, `rebase_flag`, `gate_blocked`, `file_classification`),
   `cycles`, `unresolved`, and `package_overlaps` — a structural report, not an order:
   - `cycles`/`unresolved`: hand those PRs to the maintainer by number; don't pick an
     order for them.
   - `package_overlaps`: cite the pair and path directly.
   - Within a tier, no hard dependency exists between any two PRs — order them
     yourself: `coderabbit_approved` + zero unresolved threads is a real tiebreak
     (fastest to actually land) when nothing stronger applies; a closing issue's
     `release-critical`/`-high`/`-medium`/`-low` label (not the PR's own labels — see
     `kyverno-context`) is a real urgency signal; Slack context (step 6) and
     anything the maintainer said this session override both. State which one
     decided the order.
   - `gate_blocked`: state plainly wherever true — merging is blocked branch-wide
     regardless of files touched; review work isn't. If the failure issue's content
     (job/test names) suggests this PR is unrelated, say so as your own read and
     suggest `e2e-gate-bypass` to the maintainer — never imply it's already safe,
     never apply it yourself.
5. **Diagnose every `needs-review` entry** — `pull_request_read(method="get_reviews")`
   for Copilot's verdict, `get_check_runs`/`get_status`/`get`'s mergeable-state for a
   conflict. Name the actual cause ("Copilot flagged the changelog note as missing,"
   not "not approved yet"). For `major-bump`, pull the module's own `list_releases`
   and `search_code` its real call sites in `KYVERNO_REPO` — the actual blast radius.
   A `github.com/kyverno/api` bump additionally needs: (a) `search_code` for
   `policies.kyverno.io` type/alias usage in hand-written `pkg/**` code; (b) whether
   this PR's own diff already includes the matching regenerated outputs — a
   `go.mod`/`go.sum`-only diff means they're now stale, a citable finding.
6. **Check `SLACK_HOME_CHANNEL`** for messages naming the bot or a specific PR — cite
   and apply as in step 4's within-tier rule.
7. **Produce one ordered list**, tier by tier. Every position — human or Dependabot —
   renders identically (Output format below): no separate section, no bolded
   verdict styling that singles one kind out.

Completion criterion: every fetched candidate appears exactly once, every claim
traces to a cited tool call or `sequence_prs` field, and a human could re-derive the
order from the stated reasons alone.

## Procedure: review brief (explain PR #N)

Resolves live every time — no cache across a conversation. Short form (default):
what it changes (from the fetched `body`/`changed_files`, or `pull_request_read
(method="get_diff")` if asked for the actual diff), why (its `closing_issues`, their
milestone/labels), and existing review output (CodeRabbit for security/lint/tests/
codegen, Copilot for logic/cross-file impact — say plainly if neither has reviewed it
yet).

Long form (asked for, or a signal below is concerning) adds:

- Review-thread state: `pull_request_read(method="get_review_comments")`'s
  `is_resolved` + last commenter per thread — name which threads, not just a count.
- Risk: the same file-classification/gate check as the main Procedure, for this PR.
- Slack context: `conversations_history(limit="7d")` (widen on request), matched
  client-side against the PR's number/title/URL — no server-side search exists.
  State the window checked; empty means "not mentioned in that window," not "never."
- Suggested action (approve / request changes / wait on CI / needs author to resolve
  threads / proceed but flagged as high post-merge risk), stated with its reason.
  Before drafting, `mnemosyne_recall` for durable notes on this PR's author.

## Answering open-ended questions

Look with the tools above, cite what was found — never a general prior about a
"typical" Kyverno PR. **"Is anything else related to this?"** — `search_issues` for
currently-open mentions plus `mnemosyne_recall` for closed/rejected history with a
reason. **"CI broke on `main`"** — real input, not polled for; `actions_list`/
`actions_get`/`get_job_logs` on demand, then cross-reference against the current
queue's file overlap, naming specific PRs and paths.

## Output format

- Every PR or issue mentioned gets a real link:
  `https://github.com/${KYVERNO_REPO}/pull/<n>` or `/issues/<n>` — not a bare `#n`.
- Every candidate uses the same per-position shape regardless of label or author:
  link, what it is, the cited reason(s), any `warnings`. No position gets special
  headings or verdict styling another doesn't.
- State the slice size vs. the real total whenever the set was narrowed.

## Pitfalls

- Don't assume a label exists — `kyverno-context`'s live `list_label` is the source
  of truth.
- Don't recompute the readiness workflows' own gating — use the label as the filter.
- Don't poll or loop checking post-merge CI or the gate — one on-demand call, never a
  watch.
- Never report a `needs-review` entry with just the label name — step 5's diagnosis
  runs every time.
- Don't default to oldest-first, and don't give Dependabot PRs special formatting.

## Verification

- Ask "what's my PR queue" with no other context: confirm Step 0 fires before any
  fetch. Ask again naming a milestone: confirm it fetches directly, no question.
- Build a queue with both human and Dependabot `needs-review` entries: confirm
  identical formatting.
- With an open `e2e-failure` issue: confirm `gate_blocked` is stated for every
  non-bypass PR on that branch, and any bypass read is the agent's own, not
  mechanical.
- Confirm two candidates in the same tier, differing only in `coderabbit_approved`,
  get that stated as the tiebreak.
- Confirm a closing issue's `release-critical` label is cited when present, and that
  the PR's own labels are never checked for it.
- Confirm every PR/issue number in a real answer is a working link.
- Ask about `workflow-approval-required` PRs: confirm they're named separately with
  "no tool here can approve this."
- Re-run the same queue twice with no repo-state change: confirm stable output.
- Pick two PRs touching the same `api/**` path: confirm the generated-file conflict
  is called out explicitly.
