# kyctrl

An autonomous maintainer-assistant bot fleet for `kyverno/kyverno`, built on
[Hermes Agent](https://github.com/NousResearch/hermes-agent) as the runtime,
Claude as the comment-writing layer (never the decision-maker), and GitHub
Actions as the only place privileged tokens exist.

**Status: Phase 0.** One bot — `dependabot-bot` — is fully implemented and
wired end to end: it reads a Dependabot PR's signed commit metadata,
CI status, Socket.dev supply-chain score, and GitHub Copilot's review, runs
that through a deterministic policy engine, and posts either an
`/kyctrl-merge approved` trigger comment or a flag-for-human-review
comment. It never merges anything itself — see `docs/architecture.md` for
exactly how that's enforced. The other eight bots described in `plan.md`
are scaffolded (profile directories exist) but not yet implemented.

## Quick start

See `docs/deployment.md` for the full runbook (GitHub App registration,
tunnel setup, Socket.dev key, sandbox repo). Short version:

```bash
cp .env.example .env   # fill in real values, see docs/deployment.md
./setup.sh
```

## Layout

- `config.yaml` — Hermes routing + tool grants. Security-critical, hand-edited only.
- `settings.yaml` — every bot's tunable thresholds, in one place. Safe for any maintainer to edit.
- `profiles/<bot>/` — one Hermes profile per bot (SOUL.md + model config).
- `skills/` — domain knowledge loaded into a bot's context for a given route.
- `scripts/` — deterministic engines. No LLM calls live here.
- `.github/workflows/` — where privileged GitHub actions (merge, review requests) actually run.
- `docs/architecture.md` — the security model and design decisions, in detail.
- `docs/deployment.md` — how to actually run this.
- `docs/adding-a-new-bot.md` — the pattern to follow for bot #2 onward.
