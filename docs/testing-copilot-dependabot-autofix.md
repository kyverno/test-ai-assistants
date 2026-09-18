# Testing `copilot-dependabot-autofix.yml`

What this workflow does: on a 15-minute `schedule` (plus `workflow_dispatch`
for on-demand runs), it sweeps every open Dependabot PR and checks each
one's current merge state and completed checks. If a PR has a merge
conflict or an already-failed check, it posts one `@copilot` comment asking
Copilot's coding agent to fix it in place. It never merges anything — see
`docs/architecture.md`'s security model.

It does **not** trigger on `pull_request_review` — see "Gotcha found live"
below for why that design was abandoned.

## What's already live in this repo

- `.github/workflows/copilot-dependabot-autofix.yml` — the workflow itself
  (renamed from `kyctrl-auto-merge.yml`, which no longer exists — that name
  implied merge behavior this workflow doesn't have).
- `.github/workflows/copilot-auto-request.yml` — already existed; requests
  Copilot as a reviewer on every PR, including Dependabot's, so there's
  still a real Copilot review on record for humans to read even though the
  autofix workflow itself no longer waits on that event.
- `.github/dependabot.yml` — new. Turns on real Dependabot version updates
  for `gomod` (the test fixture below) and `github-actions`.
- `examples/dependabot-test-fixture/` — a minimal Go module pinned to
  `google/uuid v1.1.0` (2019), several versions behind current. Exists only
  so Dependabot has something real to open PRs against.
- `.github/workflows/dependabot-test-fixture-ci.yml` — builds/vets the
  fixture on PRs that touch it, so there's a real check that can fail.

## Gotcha found live: `pull_request_review` doesn't work here

First version of this workflow triggered on `pull_request_review.submitted`
(react the moment Copilot finishes reviewing a Dependabot PR). Tested against
a real PR ([#2](https://github.com/kyverno/test-ai-assistants/pull/2)) and
the run never executed — [`action_required`, zero
jobs](https://github.com/kyverno/test-ai-assistants/actions/runs/35344354297).

Confirmed cause: GitHub holds any workflow run triggered by an event
associated with a Dependabot-authored PR at `action_required` until a
maintainer manually clicks "Approve and run", if that run requests a write
permission — and `pull_request_review` is explicitly one of the covered
events ([docs](https://docs.github.com/en/code-security/reference/supply-chain-security/troubleshoot-dependabot/dependabot-on-actions)).
`push`/`pull_request` got an exemption from this in 2021 (confirmed live
too: `copilot-auto-request.yml`, `permissions: pull-requests: write`,
triggers on `pull_request` and ran automatically with no approval needed on
the same PR) — but that exemption was never extended to
`pull_request_review`, `pull_request_review_comment`, or `issue_comment`.
And this isn't a one-time trust decision like the "first-time contributor"
fork gate: it needs a manual click on **every** run. Incompatible with
"fully automatic."

Fix: moved to a `schedule` sweep instead. `schedule` isn't associated with
Dependabot at all, so it's never gated. Bonus: it also closes a gap the
review-triggered design had by construction (documented in its own header
comment at the time) — a check that finishes and fails, or a conflict from
`main` moving, with no later push to produce a new review, would never
have been noticed by a review-triggered design. A sweep just looks again
next interval regardless.

Separately, worth knowing even apart from the approval gate: Copilot's
review on PR #2 was 🟡 *"Changes recommended"* (a real, correct catch —
`examples/dependabot-test-fixture/README.md` still said "pinned to v1.1.0"
after the bump) — not a merge conflict or a failing check. This workflow
only reacts to those two conditions, not to "Copilot left a review
comment" in general — so even under the old design, this particular
review wouldn't have produced a fix-request comment. That's the intended
scope, not a bug, but easy to expect otherwise from the PR's "Changes
recommended" banner.

## External steps — not something I can do from here

**1. Confirm Copilot code review is actually available for this repo.**
`copilot-auto-request.yml` calls `gh pr edit --add-reviewer @copilot`; if
Copilot code review isn't enabled for the `kyverno` org / this repo, that
call fails outright. Check: open any PR on GitHub, click the reviewers gear
icon, see if "Copilot" is offered. Already confirmed working on PR #2 (a
real review was posted), so this is done — noted for future repos.

**2. Confirm Copilot *coding agent* is enabled — separate from #1.**
Code review (#1) lets Copilot leave a review. Actually *acting* on an
`@copilot` comment (what this workflow posts) requires the coding agent
capability, its own toggle: Repository Settings → Copilot → Coding agent,
or an org-level Copilot policy. Without it, the workflow still "succeeds"
(the comment posts) but nothing happens after — looks like it worked when
it silently didn't. **Not yet confirmed**: a plain `@copilot fix this`
comment was posted manually on PR #2 and, as of this writing, produced no
new commit or visible agent activity. Someone with org admin should check
Repository/Organization Settings → Copilot → Coding agent is on before
concluding the automation is broken — this may just be the actual gap.

**3. Nothing else should be needed.** Confirmed already: repo is public,
`main` has no branch protection, and the workflow's explicit `permissions:`
block doesn't depend on the repo's default Actions token permissions.

## Test plan

### 0. Get a real Dependabot PR

In the GitHub UI: Insights → Dependency graph → Dependabot → find the
`gomod` update → "Check for updates" (don't wait for the daily schedule).
This opens a PR bumping `google/uuid` toward `v1.6.x`. (Already done once —
PR #2 — safe to do again for a fresh run once that one's closed.)

### 1. Baseline: happy path (nothing broken)

Trigger the sweep on demand instead of waiting for the cron tick: Actions
tab → "Copilot Dependabot autofix" → "Run workflow". For a fresh, unbroken
`uuid` bump, expect the log to say *"Nothing broken"* and move on — this
confirms the sweep, the `gh pr list` author filter, and the merge/check
reads all work before testing the interesting paths.

### 2. Failing-check path

While a Dependabot PR is open: `gh pr checkout <PR#>`, break the build on
purpose (e.g. a syntax error in `examples/dependabot-test-fixture/main.go`),
commit, push to the Dependabot branch. `dependabot-test-fixture-ci.yml`
will fail. Run the sweep on demand (or wait up to 15 minutes) — it should
find a `FAILURE` check and post the `@copilot` comment. Revert the breaking
change afterward (or let Copilot's fix, if agent mode is on, do it).

### 3. Merge-conflict path

While the PR is open, edit `examples/dependabot-test-fixture/go.mod` (or
`main.go`) directly on `main` in a way that touches the same lines
Dependabot's PR changed, and push. Run the sweep on demand — it should see
`mergeStateStatus: DIRTY` and post the comment. (This is the exact
scenario the old review-triggered design couldn't have caught without a
lucky re-review — confirms the fix actually fixed something.)

### 4. Idempotency

Run the sweep again with no new commit on the PR. It should log *"Already
asked Copilot about commit \<sha\>, skipping."* — confirms the HTML-comment
marker dedup works.

### 5. Coding agent follow-through (needs external step #2 confirmed)

Watch for Copilot to push a new commit to the PR branch within roughly
5–15 minutes of the `@copilot` comment. Note: the comment's fix
instructions mention `make codegen-*` targets — carried over from the
eventual `kyverno/kyverno` use case, doesn't apply to this fixture repo.
Harmless for testing the automation mechanics.

### Cleanup

Close/delete test PRs when done. Dependabot will keep proposing `uuid`
bumps on its daily schedule going forward — expected, fine to leave running
as an ongoing live test signal; add an `ignore` rule in
`.github/dependabot.yml` later if you want to stop it. The 15-minute
`schedule` will also keep running indefinitely — tighten or remove it once
testing is done if the Actions minutes usage matters.

## Known stale references, not touched here

`plan.md`, `README.md`, `docs/adding-a-new-bot.md`, and
`profiles/dependabot-bot/SOUL.md` still describe the old
`/kyctrl-merge approved` → `gh pr merge` design from the deferred
Hermes-based `dependabot-bot`. That's a separate, larger initiative from
this workflow and wasn't touched — flagging in case it's worth reconciling
later.
