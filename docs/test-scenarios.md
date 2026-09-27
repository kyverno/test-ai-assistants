# Test scenarios

A fake environment built on `kyverno/test-ai-assistants` itself, shaped to
exercise `pr-queue`/`kyverno-context`/`pr-actions` for real rather than
guessing whether the reasoning works. Everything here is tagged `[test]` in
its title so it's easy to tell apart from the repo's other (unrelated)
dependabot-autofix test fixtures.

## Important: "what's my review queue" won't surface any of these

GitHub blocks requesting a review from a PR's own author. All the test PRs
below were created by the same account configured as
`MAINTAINER_GITHUB_LOGIN`, so `review-requested:` — the query `pr-queue`
uses to find candidates — returns zero for all of them. Verified directly
against GitHub's search API, not assumed. This is a platform rule, not a
bug: solo-testing hits it by construction. Address PRs by number instead of
asking for "the queue" as a first pass; everything else below still
exercises the real reasoning.

## Scaffolding (merged to `main`, PR #11)

- `CODEOWNERS` — three specificity levels (`*`, `/skills`,
  `/skills/pr-actions`), each a different owner, to test last-match-wins
  for real rather than by inspection.
- `api/` — mirrors `kyverno/kyverno`'s real codegen-fanout trigger path
  (see `skills/kyverno-context/SKILL.md`).
- `.github/workflows/check-codegen.yaml` / `check-tests.yaml` — mirror the
  real pre-merge / post-merge-only workflow *names* `kyverno-context`
  already references, so CI-status queries match something real. No real
  codegen or test suite runs in either — both are no-ops on purpose.

## Readiness labels (mirrored from the real taxonomy)

`ready-for-review`, `needs-review`, `major-bump`, `ai-generated`, `spam` now
exist on this repo, alongside the `needs-author-action`/`merge-conflicts`
pair already here from the readiness-check fixtures (#4-#6). `pr-queue`'s
merge-sequencing candidate set (`label:ready-for-review` /
`label:needs-review`) resolves against real labels here, not an empty set.

## Scenarios

| Scenario | PRs/Issues | Try asking |
|---|---|---|
| Generated-file conflict | #12, #13 (both touch `api/`, non-overlapping files) | "explain #12 and #13 together — do they conflict?" |
| Stacked PR | #14, #15 (#15's base branch is #14's head branch) | "is #15 stacked on anything?" |
| Package overlap | #16, #17 (both touch `pkg/shared`, different files, no git conflict) | "do #16 and #17 overlap?" |
| Post-merge CI risk — **honesty test** | #18 (touches `pkg/engine`) | "does #18 put anything at post-merge risk?" — `kyverno-context` has post-merge-only workflow *names* but no explicit path-to-suite mapping, so watch whether it says that plainly instead of fabricating a confident risk claim |
| Duplicate closing-issue | #19 (issue), #20 and #21 (both PRs say "Closes #19") | "explain #20" — should surface #21 as duplicate effort via `issue_read`'s `closed_by_pull_requests` |
| Related but unlinked | #22 (issue, discusses the same area as #18, no formal link) | "is anything else related to #18?" |
| Milestone-alignment | #23 (issue, milestoned `Kyverno Release 1.0.0`, references #24), #24 (issue, unmilestoned), #25 (PR, closes #23 directly, `ready-for-review`), #26 (PR, closes #24, `ready-for-review`) | "build the merge sequence" — #25 should rank ahead of #26 on milestone-alignment, with the tiebreak reasoning stated inline |
| CODEOWNERS last-match | n/a — ask directly | "who owns `skills/kyverno-context/SKILL.md`" → should resolve to the `/skills` line's owner, not the `*` fallback |
| Taking action (`pr-actions`) | any PR above | "label #16 as kind/bug" (already has it — should notice), "approve #17", "rebase #15" (watch for the honest "this is a merge-update, not a real rebase" framing) |

## Known gap this setup deliberately surfaces

`pr-queue`'s post-merge-CI-risk reasoning is only as good as
`kyverno-context`'s post-merge-only-suite reference, which currently names
workflow *files*, not the code *paths* those suites actually exercise. The
#18 scenario above exists specifically to observe how the assistant handles
that gap — a real thing to fix once observed, not something to paper over
in this doc.
