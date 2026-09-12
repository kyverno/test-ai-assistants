#!/usr/bin/env bash
# kyctrl — one-command local setup for Phase 0.
#
# Syncs the tracked config (config.yaml, settings.yaml, mcp.json, SOUL.md,
# distribution.yaml, profiles/, skills/, scripts/) into .hermes-data/,
# Hermes's actual runtime data directory (gitignored, mounted as
# /opt/data — see docker-compose.yml's header comment for why this is a
# separate directory and not the repo root), then starts the gateway.
#
# The sync is one-directional and additive (rsync without --delete): repo
# files overwrite their counterparts in .hermes-data/, but Hermes's own
# runtime state living alongside them (sessions/, memories/, state.db,
# its bundled skills, etc.) is left untouched. Re-run this script any time
# you change config.yaml, settings.yaml, a skill, or a script.
#
# What this does NOT do (these are manual, see docs/deployment.md):
#   - register the @kyctrl-bot GitHub App
#   - start the ngrok tunnel
#   - create Socket.dev / GitHub tokens

set -euo pipefail
cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required — install Docker Desktop (or Docker Engine) first." >&2
  exit 1
fi

if [ ! -f .env ]; then
  echo "No .env found — copying .env.example to .env."
  cp .env.example .env
  echo
  echo "Now edit .env and fill in at least:"
  echo "  ANTHROPIC_API_KEY, GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY_PATH,"
  echo "  GITHUB_WEBHOOK_SECRET, KYCTRL_READONLY_GITHUB_TOKEN, SOCKET_DEV_API_KEY"
  echo
  echo "See docs/deployment.md for where each of these comes from, then re-run this script."
  exit 0
fi

mkdir -p .hermes-data
echo "Syncing tracked config into .hermes-data/ (Hermes's runtime data dir)..."
rsync -a \
  config.yaml settings.yaml mcp.json SOUL.md distribution.yaml \
  profiles skills scripts \
  .hermes-data/
cp .env .hermes-data/.env

echo "Starting kyctrl (Hermes gateway) via docker compose..."
HERMES_UID="$(id -u)" HERMES_GID="$(id -g)" docker compose up -d

echo
echo "Gateway starting on :8644 (webhook routes) and :8642 (gateway API)."
echo "Tail logs with:  docker compose logs -f gateway"
echo
echo "Next steps if you haven't done them yet (see docs/deployment.md):"
echo "  1. Expose :8644 publicly (ngrok tunnel) so GitHub can reach it."
echo "  2. Register the @kyctrl-bot GitHub App using that public URL."
echo "  3. Install the App on your sandbox repo and open a test Dependabot-style PR."
