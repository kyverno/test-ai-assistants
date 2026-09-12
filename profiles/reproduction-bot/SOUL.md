# reproduction-bot — not yet implemented (build plan Phase 2)

Will fire on `issue_comment` events whose body contains `/kyctrl-reproduce`
(posted by triage-bot, or by a maintainer directly). Runs
`scripts/yaml-extractor.py` to deterministically pull policy/resource YAML
out of the issue body, then posts structured parameters for the
`.github/workflows/kind-reproduction.yml` Actions workflow to pick up.

This is the concrete test of the trigger-comment handoff pattern: triage-bot
and reproduction-bot are two separate webhook-triggered Hermes sessions —
Hermes's A2A messaging does not reliably bridge that, so the handoff has to
be a real GitHub comment triggering a real second webhook, not a direct
agent-to-agent call. See `docs/architecture.md`.
