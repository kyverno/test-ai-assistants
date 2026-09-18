# Dependabot test fixture

Not part of kyctrl. Exists solely to give the `gomod` ecosystem a real,
outdated dependency (`google/uuid` pinned to `v1.1.0`) so Dependabot opens
real PRs against this repo, which is what
`.github/workflows/copilot-dependabot-autofix.yml` needs to react to.
See `docs/testing-copilot-dependabot-autofix.md` for the test plan.
