# coach-bot — not yet implemented (build plan Phase 3)

Will fire on `pull_request.opened` from human contributors: check
contributor memory (first-timer? DCO history?), detect AI-generated PRs,
gate on codegen for `api/` changes, and read GitHub Copilot's review
comments (via `skills/copilot-review-check.md`, shared with every
PR-touching bot) to synthesize Kyverno-specific context for the
contributor.

See `docs/adding-a-new-bot.md` for the pattern to follow and `plan.md` /
the build plan for this bot's full spec. `dependabot-bot` is the reference
implementation of the "checked Copilot's review first" pattern this bot
also needs.
