# Testing guide

Prompts to exercise every capability, each grounded in real, current counts on
`kyverno/kyverno` (pulled live while writing this). These numbers drift as PRs
merge/open — re-check with the same `fetch_pr_candidates`/`gh` calls if testing
much later and a result looks off.

## 1. Focus (Step 0)

- **"what is my pr queue"** (nothing else said)
  Expect: a clarifying question — milestone, author, area, or
  workflow-approval-required — before any fetch. No default sort.
- **"show me PRs for milestone Kyverno Release 1.20.0"**
  Expect: fetches directly via `milestone:"Kyverno Release 1.20.0"`, no
  question. Real: exactly 1 ready-for-review PR currently (#17770).
- **"show me PRs by vishalmore90"**
  Expect: fetches directly, `author:` qualifier. Real: 7 ready-for-review PRs
  currently — the most of any author right now.
- **"show me PRs touching pkg/engine"**
  Expect: fetches the normal candidate set, then filters `changed_files`
  client-side (no GitHub path qualifier exists).
- **"show me PRs waiting on workflow approval"**
  Expect: `workflow-approval-required` fetched separately, named as its own
  list, never passed into `sequence_prs`. Real: 50 open right now; 19 of
  those also carry `needs-author-action` — confirm both labels get named on
  those 19, not just one.

## 2. Author association

- **"who authored these PRs, anyone I should look at closer"**
  Real right now: PR #17785's author is a `FIRST_TIME_CONTRIBUTOR`; #17770's
  author is a `MEMBER`. Expect both cited, and the first-time contributor's
  PR named as worth a closer look without that being the only thing said
  about it — not an automatic deprioritization.

## 3. Gate check

- **"what is my pr queue"**, any focus
  Expect: a `list_issues(state="open", labels=["e2e-failure"])` call —
  *not* `search_issues` (natural-language only, proven unreliable here: it
  previously reported "no open gate issue" when one genuinely was open).
  Real right now: issue #17821 is open, body marker
  `refs/heads/main` — so `gate_blocked: true` on every non-bypass PR
  targeting `main`, and `false` on anything targeting another branch.
- Ask directly: **"is the e2e gate open right now"**
  Expect: cites #17821 by link, states it blocks `main` specifically (not
  every branch — this issue has a real marker).

## 4. needs-review diagnosis

- **"what's blocking the needs-review PRs"**
  Real: exactly 1 open right now, #17763 ("bump the kubernetes group across 2
  directories"), Dependabot, real CI failure, not CodeRabbit-approved, not
  `major-bump`. Expect: the actual cause named (failing CI / a specific
  mixed-dependency finding if Copilot flagged one), not just "not approved
  yet."
- `major-bump` test: none currently open. Expect the agent to say so plainly
  if asked to find one, not fabricate an example.

## 5. CodeRabbit approval (the login-string bug, fixed)

- **"show me only coderabbit approved prs"**
  Real right now: 14 of 101 fetched ready-for-review+needs-review PRs are
  genuinely approved, including #17785, #17789, #17791, #17809, #17754,
  #17777. Expect a non-empty, correct list — this is the exact bug that
  previously reported zero.
- Within a tier with no hard dependencies, confirm an approved PR is
  ordered ahead of a plain one with the stated reason.

## 6. CI-state accuracy (the gate-bleed-through bug, fixed)

- Ask about **PR #17770** specifically ("why does this show a CI failure")
  while the gate is open. Expect: `ci_state: SUCCESS` — the agent should
  *not* report a false CI failure caused by the gate's own status context.
- A genuine edge case to probe: **PR #17840** currently carries
  `ready-for-review` *and* a real (non-gate) CI failure — ask about it and
  confirm the agent reports the real failure honestly instead of assuming
  the label guarantees current cleanliness (the readiness sweep runs
  hourly; state can drift between runs).

## 7. File vs. package overlap

- **"do any of the open PRs conflict on the same file"**
  Real: PR #16463 shares `cmd/kyverno/main.go` with #17128/#17551/#17695/
  #17770/#17774, and `pkg/controllers/webhook/utils.go` with #17133/#17207/
  #17457 — a real multi-PR hot file. Expect `file_overlaps` entries, then
  `fetch_file_diff_overlap` called per pair before presenting — it returns
  raw patches only (no computed line-overlap verdict; that math turned out
  unreliable across independent merge-bases), so expect the agent to read
  both and describe what's actually colliding, not a bare yes/no.
- **"what about PRs in the same area but different files"**
  Real: #16437/#16440/#17258/#17322 all touch `pkg/utils/report` without
  sharing a file. Expect `package_overlaps`, phrased as a softer
  "review together" note — not conflated with a real file overlap, and
  `fetch_file_diff_overlap` should *not* be called for these (no shared
  file to compare).
- Confirm cost stays bounded: ask for the full queue and count the
  `fetch_file_diff_overlap` calls — should match the number of real
  `file_overlaps` entries worth checking, not one per PR or per pair overall.

## 8. Hard edges

- **Explicit body reference**: real right now — PR #17774's body says
  "Stacks on top of #17695" and both are candidates; expect
  `"must follow #17695 (explicit reference)"` on #17774.
- **Cross-repo-qualified reference**: PR #17721's body says "depends on
  kyverno/kyverno#17720" — #17720 itself is *not* ready-for-review (it
  carries `needs-author-action`), so ask about #17721 specifically and
  confirm `external_references` resolves #17720's real state (open issue
  vs. PR) rather than treating the reference as unresolvable or ignoring
  the `owner/repo#N` form.
- **Stacked branches**: #17721's base branch is #17720's head branch — a
  real stacked pair. Fetching only `label:ready-for-review` won't surface
  this edge (#17720 isn't a candidate); ask for a queue that includes
  `needs-author-action` too and confirm the stacked edge appears. Good test
  of the real limitation: a stacked edge only forms when *both* PRs are in
  the fetched set.
- **Generated-file input-before-output**: real right now — #17669 (a
  generated-input PR) precedes #17000, #17540, #17770, and #17778 in the
  actual tier output. Ask for the full ready-for-review queue and confirm
  all four show `"must follow #17669 (generated-file)"`.
- **Ambiguous generated-input pairs → `unresolved`**: #17669, #17000, and
  #17778 *also* all pairwise-touch a generated-file input with no
  derivable order between each other (on top of the edges above) — confirm
  these three pairs land in `unresolved`, not guessed into an order.
- **Closing-issue conflict**: three real pairs right now — (#16711, #16712)
  both close #16710; (#16896, #16955) both close #16895; (#17366, #17789)
  both close #17345. Ask about any of these and confirm `unresolved` names
  the shared issue, with neither PR ordered relative to the other.

## 9. Review brief

- **"explain PR #17029"** (short form)
  Real: carries `ready-for-review` but shows `unresolved_review_threads: 1`
  — because the one unresolved thread's last comment is the author's own
  reply, which `pr-readiness-check.yaml` doesn't treat as blocking. Ask the
  long form ("explain PR #17029 in detail") and confirm the agent names
  this distinction (thread technically open, last comment is the author's)
  rather than reporting a bare count.
- **"is anything else related to PR #17755"**
  Expect `search_issues` for open mentions plus `mnemosyne_recall` for
  closed/rejected history, cited separately — an empty Mnemosyne result
  stated as "nothing found," not silently skipped.

## 10. Conversational / memory

- **"CI broke on main, what's affected"**
  Expect `actions_list`/`get_job_logs` on demand, then cross-referenced
  against the current queue's real file overlap — not a generic "some PRs
  might be affected."
- **"remember that I'm prioritizing pkg/cel this week"**, then later in a
  new session, **"what's my current focus"**
  Expect a real `mnemosyne_remember`/`recall` round trip, staged for
  approval per `write_approval: true` if that's still configured.
- **"what are the conventions for pkg/engine"**
  Expect `mnemosyne_recall` for `kyverno-doc:pkg/engine/AGENTS.md` first —
  not an immediate `search_code` call.

## 11. Orphaned labels

- Find a PR whose closing issue carries `release-critical` (several exist
  historically) and ask about it. Expect the agent to cite it as a real,
  manually-applied urgency signal from the issue — and, if asked whether
  it's part of the managed taxonomy, to say plainly that it isn't (absent
  from `.github/labels.yml`, no workflow governs it).

## 12. Action boundaries (`pr-actions`)

- **"merge PR #17785"** — expect a plain decline: no merge tool exists.
- **"commit a fix to PR #17763"** — expect a plain decline: no file-write
  tool exists.
- **"label PR #17785 as totally-made-up-label"** — expect `kyverno-context`'s
  live `list_label` checked first, and the action refused rather than
  calling `issue_write` with a label that doesn't exist.
- **"rebase PR #17770 onto main"** — this PR touches `charts`/`.github`
  paths; expect a codegen-staleness warning before (and restated after) the
  `update_pull_request_branch` call, and "update the branch" language, not
  "rebase" (it's a merge-update, not a real rebase).

## 13. Discussions

- **"what's discussion #17274 about"** ("Should 1.20.0 be a major
  release?" — one of 222 currently open) — expect a cited summary, not a
  guess, and an offer to reply only after showing a draft.

## 14. Cron / digest

`kyverno-review-digest`, `kyverno-memory-sweep`, `kyverno-memory-consolidate`
ship paused. Can't test live output without resuming one
(`hermes -p kyverno cron resume <job-id>`) — if you do, expect the digest to
use the fixed fallback (no focus to ask about, so it defaults to
release-urgency + review-readiness + most-recently-updated, never
oldest-first).

## 15. Historical post-merge risk

- Ask about an `ADMISSION_CRITICAL`-classified PR (e.g. one touching
  `pkg/engine`): confirm `mnemosyne_triple_query` runs for `caused_e2e_failure`
  on that package, and the result is stated either way — a real incident
  cited, or "nothing found" — never skipped.

## 16. Milestone urgency

- Real right now: #17770 is under "Kyverno Release 1.20.0" (due 2026-10-23),
  #17856 under "Kyverno Release 1.19.2" (due 2026-10-12) — the sooner one.
  Ask for a queue containing both and confirm the near-due milestone is cited
  as a reason #17856 ranks earlier, not just "has a milestone."

## 17. PR size as review effort

- Real right now: #17770 (67 files, 2257+/919-) and #17774 (54 files,
  3000+/183-) are both large; most of the rest of the queue is under 10
  files. Ask about either and confirm size is named as a "needs a dedicated
  session" signal, distinct from merge priority.

## 18. The precedence ladder, against a real known-bad case

A real session (audited, not hypothetical) ranked #17856 (a milestone-tagged
PolicyException bug, CodeRabbit `CHANGES_REQUESTED`) ahead of #17860 (an
admission-controller crash — `fatal error: concurrent map writes` — MEMBER
author, CodeRabbit-approved), and ranked #17857 (a real 1.19 regression
requesting cherry-pick) and #17791 (a dry-run security bypass) below several
routine CLI fixes with no milestone or CodeRabbit gap in their favor.

- Ask for the full ready-for-review queue and check these specific PRs'
  relative order. Expect, by the ladder: #17860 (`CRITICAL` — crash) ranks
  above #17856 (no crash/security label, and CodeRabbit flagged concerns —
  shouldn't appear in an "approve now" grouping regardless of its milestone).
  #17857 and #17791 (`HIGH` — regression / security bypass) should rank above
  routine `MEDIUM`/`LOW` CLI fixes, not below them.
- Confirm #17831/#17838 (same author, same file, same kind of CLI fix) are
  presented as one adjacent cluster, not as separate positions with the
  connection re-explained from scratch at each one.
