# Testing `copilot-dependabot-autofix.yml`

What this workflow does: when Copilot finishes reviewing a Dependabot PR
(`pull_request_review.submitted` from `copilot-pull-request-reviewer[bot]`),
it checks that PR's current merge state and completed checks. If either is
broken, it posts one `@copilot` comment asking Copilot's coding agent to fix
it in place. It never merges anything — see `docs/architecture.md`'s
security model.

## What's already live in this repo

- `.github/workflows/copilot-dependabot-autofix.yml` — the workflow itself
  (renamed from `kyctrl-auto-merge.yml`, which no longer exists — that name
  implied merge behavior this workflow doesn't have).
- `.github/workflows/copilot-auto-request.yml` — already existed; requests
  Copilot as a reviewer on every PR, including Dependabot's. This is what
  produces the `pull_request_review` event the autofix workflow listens for.
- `.github/dependabot.yml` — new. Turns on real Dependabot version updates
  for `gomod` (the test fixture below) and `github-actions`.
- `examples/dependabot-test-fixture/` — a minimal Go module pinned to
  `google/uuid v1.1.0` (2019), several versions behind current. Exists only
  so Dependabot has something real to open PRs against.
- `.github/workflows/dependabot-test-fixture-ci.yml` — builds/vets the
  fixture on PRs that touch it, so there's a real check that can fail.

## External steps — not something I can do from here

**1. Confirm Copilot code review is actually available for this repo.**
`copilot-auto-request.yml` calls `gh pr edit --add-reviewer @copilot`; if
Copilot code review isn't enabled for the `kyverno` org / this repo, that
call fails outright and nothing downstream ever fires. Check: open any PR
on GitHub, click the reviewers gear icon, and see if "Copilot" is offered
as a reviewer. If it isn't, an org owner needs to enable it — Organization
Settings → Copilot → Policies (org-level), or Repository Settings →
Copilot → Code review (repo-level, if the org allows per-repo control).

**2. Confirm Copilot *coding agent* is enabled — separate from #1.**
Code review (#1) lets Copilot leave a review. Actually *acting* on an
`@copilot` comment (the thing this workflow posts) requires the coding
agent capability, which is its own toggle: Repository Settings → Copilot →
Coding agent, or an org-level Copilot policy. Without it, the workflow
will still "succeed" (the comment gets posted) but nothing ever happens
after that — it'll look like it worked when it silently didn't. Quick way
to check: comment `@copilot` with a small ask on any issue or PR yourself
and see whether Copilot picks it up (usually visible within a few minutes
as an assigned session / new commit). If nothing happens, someone with org
admin needs to turn this on.

**3. Nothing else should be needed.** Confirmed already: repo is public,
`main` has no branch protection, and the workflow's explicit `permissions:`
block doesn't depend on the repo's default Actions token permissions.

## Test plan

### 0. Get a real Dependabot PR

Push these changes, then in the GitHub UI: Insights → Dependency graph →
Dependabot → find the `gomod` update → "Check for updates" (don't wait for
the daily schedule). This should open a PR bumping `google/uuid` toward
`v1.6.x`.

### 1. Baseline: happy path (nothing broken)

- Watch the Actions tab: `copilot-auto-request.yml` should run first,
  requesting Copilot's review.
- Once Copilot posts its review (can take a few minutes),
  `copilot-dependabot-autofix.yml` should run. Since a fresh `uuid` bump has
  no conflict and CI should pass, expect its log to say *"Nothing broken as
  of this review"* and exit — this confirms the trigger and the
  read-only checks work before testing the interesting paths.

### 2. Failing-check path

While the PR is still open: `gh pr checkout <PR#>`, break the build on
purpose (e.g. a syntax error in `examples/dependabot-test-fixture/main.go`),
commit, push to the Dependabot branch. `dependabot-test-fixture-ci.yml`
will fail; Copilot re-reviews automatically on the new push; the autofix
workflow should now find a `FAILURE` check and post the `@copilot` comment.
Revert the breaking change afterward (or let Copilot's fix, if agent mode
is on, do it).

### 3. Merge-conflict path

While the PR is open, edit `examples/dependabot-test-fixture/go.mod` (or
`main.go`) directly on `main` in a way that touches the same lines
Dependabot's PR changed, and push. This does **not** trigger a new
Copilot review by itself (no push happened on the PR branch — this is the
exact gap the workflow's header comment calls out). Manually re-request
the review (`gh pr edit <PR#> --add-reviewer @copilot`, or re-run
`copilot-auto-request.yml` from the Actions tab) to fire a fresh
`pull_request_review` event. The autofix workflow should now see
`mergeStateStatus: DIRTY` and post the comment.

### 4. Idempotency

Re-request Copilot's review again without any new commit landing (same
head SHA). The workflow should log *"Already asked Copilot about commit
\<sha\>, skipping."* — confirms the HTML-comment marker dedup works.

### 5. Coding agent follow-through (needs external step #2 done)

If coding agent is enabled, watch for Copilot to push a new commit to the
PR branch within roughly 5–15 minutes of the `@copilot` comment. Note: the
comment's fix instructions mention `ARCHITECTURE.md` and `make codegen-*`
targets — that's carried over from the eventual `kyverno/kyverno` use case
and doesn't apply to this fixture repo (no such file/targets exist here).
Harmless for testing the automation mechanics; Copilot will just not find
them and proceed with whatever's actually broken.

### Cleanup

Close/delete test PRs when done. Dependabot will keep proposing `uuid`
bumps on its daily schedule going forward — that's expected and fine to
leave running as an ongoing live test signal; add an `ignore` rule in
`.github/dependabot.yml` later if you want to stop it.

## Known stale references, not touched here

`plan.md`, `README.md`, `docs/adding-a-new-bot.md`, and
`profiles/dependabot-bot/SOUL.md` still describe the old
`/kyctrl-merge approved` → `gh pr merge` design from the deferred
Hermes-based `dependabot-bot`. That's a separate, larger initiative from
this workflow and wasn't touched — flagging in case it's worth reconciling
later.
