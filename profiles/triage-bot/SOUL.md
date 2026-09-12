# triage-bot — not yet implemented (build plan Phase 1)

This profile is scaffolded but has no working route in `config.yaml` and no
real skill content yet. It will fire on `issues.opened`, run
`scripts/issue-fsm.py` to check for missing Kyverno fields (version, K8s
version, policy YAML, resource YAML, actual vs expected), and post either a
missing-info request or a `/kyctrl-reproduce` trigger comment.

See `docs/adding-a-new-bot.md` for the pattern to follow (it's the same one
`dependabot-bot` already uses) and `plan.md` / the build plan for this
bot's full spec. Do not enable a webhook route for this profile until
`scripts/issue-fsm.py` and `skills/kyverno-triage.md` +
`skills/kyverno-field-checklist.md` exist.
