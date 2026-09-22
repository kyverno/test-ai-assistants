# kyctrl Phase 0 notes (archived)

kyctrl was an earlier design for this repo: a 9-bot Hermes fleet driven by
GitHub webhooks (`plan.md`, `profiles/*`, `distribution.yaml`,
`docker-compose.yml`, `settings.yaml`, `scripts/dependabot-policy-engine.py`,
per-bot `skills/*.md` — all removed from the tree). Only `dependabot-bot`
(Phase 0) was ever wired up before the project moved to the current design:
first plain GitHub Actions + Copilot automation
(`.github/workflows/dependabot-autofix.yml`,
`.github/workflows/copilot-auto-request.yml`), then **kyverno-assistant**
(see `docs/architecture.md`), a maintainer-installed Hermes profile
distribution instead of a webhook-triggered fleet.

This file keeps the operational knowledge from actually running Hermes in
Phase 0, since most of it is true of Hermes generally, not specific to
kyctrl's abandoned design.

## Security principle carried forward

kyctrl's core rule — **the LLM/agent process never holds a token that can
take an irreversible, privileged action** — is why kyverno-assistant's
`config.yaml` grants no merge tool at all, rather than relying on a prompt
instruction. The mechanism kyctrl used for privileged actions: the bot posts
a trigger comment (e.g. `/kyctrl-merge approved`); a separate GitHub Actions
workflow, watching for that exact string and the bot's login, does the
actual privileged call with `GITHUB_TOKEN` — a token that only exists inside
the Actions runner and never reaches the agent. This is the pattern
kyverno-assistant's v2 merge design should follow.

## Hermes gotchas found live (Phase 0)

- A webhook route bound to a non-default profile (`profile: X` in
  `config.yaml`) is only reachable at `/p/X/webhooks/<route>`, not the plain
  `/webhooks/<route>` path.
- `config.yaml` does not expand `${VAR}` — secrets written there must be
  literal values, not env references.
- Each profile needs its own `.env` with a model API key; `model.default`
  in `config.yaml` alone isn't enough — without a key, runs fail with "No
  inference provider configured".
- The base Hermes Docker image has no `gh` CLI installed.
- A GitHub App has exactly one webhook URL total — fanning out to multiple
  bots/routes needs a router in front (Hookdeck was used here) rather than
  registering multiple Apps.
- Self-hosting Hermes via `docker-compose.yml`: `/opt/data` inside the
  container isn't just config — Hermes writes everything there (state DBs,
  per-profile sessions/memory, caches, cron/kanban state, a `lazy-packages/`
  venv, and ~60 bundled skills on first boot). Mounting the repo root
  directly as `/opt/data` pollutes the tracked tree; use a gitignored data
  directory synced from tracked config by a setup script instead of mounting
  the repo directly.

## What's not carried forward

kyctrl's multi-bot-fleet specifics — `settings.yaml` (per-bot tunable
thresholds), `scripts/dependabot-policy-engine.py` (deterministic merge
policy engine), the Hookdeck/GitHub-App webhook delivery setup, and the
9-profile `multiplex_profiles` gateway config — don't apply to
kyverno-assistant, which is a single-profile, maintainer-installed,
on-demand distribution with no webhook receiver at all. They're recorded
here only in case a webhook-triggered bot design returns later.
