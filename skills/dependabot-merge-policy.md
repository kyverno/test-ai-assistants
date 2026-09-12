# Dependabot merge policy

Context for `dependabot-bot` on why the verdict in `kyctrl_verdict` was
reached. You are not re-deciding anything here — this explains the
engine's reasoning so your comment can cite it accurately.

## Why signed commit metadata, not the PR title

`dependabot/fetch-metadata`-style parsing reads the **commit message**
Dependabot writes (structured `dependency-name:` / `dependency-type:` /
`update-type:` trailers), not the PR title. Dependabot's title generation
has known bugs on grouped/multi-directory updates where the title can be
generic or misleading while the commit body is correct. The policy engine
always trusts the commit metadata over the title — if your prompt's
verdict data and the PR title in the payload seem to disagree, trust the
verdict.

## What makes an ecosystem/update eligible at all

`settings.yaml`'s `dependabot_bot.auto_merge_ecosystems` is an allowlist —
anything not on it always FLAGs, regardless of score or CI, because the
engine doesn't understand that ecosystem's blast radius well enough to
auto-approve. `always_flag_update_types` (major version bumps by default)
always FLAGs too, independent of every other signal — a clean Socket.dev
score doesn't make a breaking change safe to merge unattended.

## What APPROVE actually means

APPROVE means: the update is on an allowed ecosystem, isn't a flagged
update type, CI is green (if `require_ci_pass` is set), the Socket.dev
score cleared the threshold, and Copilot's review didn't raise a flagged
concern (see `copilot-review-check.md`). It does not mean a human looked at
the diff — say so plainly if asked, don't imply more scrutiny happened
than did.
