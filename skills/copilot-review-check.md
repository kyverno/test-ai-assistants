# Copilot review check (shared across every PR-touching bot)

This skill isn't dependabot-bot-specific — every bot that reasons about a
PR (coach-bot, merge-queue-bot, later) uses the same check: read GitHub
Copilot's review on the PR before doing anything else, because it's the
one signal that actually looked at the diff.

## What the engine does

For dependabot-bot, `scripts/dependabot-policy-engine.py` fetches PR
reviews via the GitHub API and keeps only ones from a login listed in
`settings.yaml`'s `global.copilot_review_bot_logins`. If any such review's
body, or any of its inline comments, contains a case-insensitive match for
one of `dependabot_bot.copilot_flag_keywords` (e.g. "vulnerability",
"breaking", "security", "do not merge"), the verdict is downgraded to FLAG
— even if every deterministic check (metadata, semver, CI, Socket.dev)
otherwise passed.

## Why this is a downgrade-only gate, not a replacement

Copilot's review is a second opinion layered on top of the deterministic
checks, not a substitute for them: it can catch something none of the
structured signals would (a subtle behavioral change described in prose),
but it can also simply not have run yet, or have nothing to say on a
genuinely trivial bump. Absence of a Copilot review, or a review with no
flagged keywords, is not itself a reason to FLAG — it just means this
particular gate didn't trigger. If no Copilot review exists yet when the
policy engine runs, say so in the comment rather than implying one was
checked and came back clean.
