#!/bin/bash
# Idempotent installer for the kyverno-assistant Hermes profile. Re-run this
# same script after each step it asks you to do (fill in .env, etc.) — it
# detects what's already done and only does what's left.
set -uo pipefail

PROFILE="${1:-kyverno}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE_DIR="$HOME/.hermes/profiles/$PROFILE"

pass() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$1"; }
info() { printf '  %s\n' "$1"; }
step() { printf '\n\033[1m%s\033[0m\n' "$1"; }

cd "$REPO_ROOT" || exit 1
if [ ! -f distribution.yaml ]; then
  fail "distribution.yaml not found — run this from the repo root (or via ./scripts/install.sh)"
  exit 1
fi

step "1. Prerequisites"

if ! command -v hermes >/dev/null 2>&1; then
  fail "hermes CLI not found on PATH — install it: https://hermes-agent.nousresearch.com"
  exit 1
fi
pass "hermes CLI found ($(hermes --version 2>&1 | head -1))"

if ! command -v docker >/dev/null 2>&1; then
  fail "docker not found on PATH — the GitHub/Slack MCP servers run as containers"
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  fail "docker is installed but not running — start Docker and re-run this script"
  exit 1
fi
pass "docker is running"

step "2. Profile install"

if [ -d "$PROFILE_DIR" ]; then
  info "profile '$PROFILE' already installed — pulling in any repo changes (skills, config.yaml,"
  info "plugins/, cron) since the last install/update..."
  if ! hermes profile update "$PROFILE" --force-config -y; then
    fail "hermes profile update failed — see output above"
    exit 1
  fi
  pass "profile '$PROFILE' updated (config.yaml, skills, plugins/, cron refreshed; .env untouched)"
else
  info "installing profile '$PROFILE'..."
  if ! hermes profile install . --name "$PROFILE" --alias -y; then
    fail "hermes profile install failed — see output above"
    exit 1
  fi
  pass "profile '$PROFILE' installed"
fi

# Hermes' own bundled-essentials seed only fires when a profile's skills/ is
# fully empty — ours ships 4 skills at install time, so that check never
# triggers and Hermes' one pinned "essential" skill (hermes-agent) never
# lands. Force it explicitly (confirmed via a real fresh-install test).
hermes -p "$PROFILE" skills reset hermes-agent --restore --yes >/dev/null 2>&1
pass "essential Hermes skills present"

step "3. Credentials"

ENV_FILE="$PROFILE_DIR/.env"
ENV_EXAMPLE="$PROFILE_DIR/.env.EXAMPLE"

if [ ! -f "$ENV_FILE" ]; then
  if [ -f "$ENV_EXAMPLE" ]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    info "created $ENV_FILE from .env.EXAMPLE"
  else
    fail "$ENV_EXAMPLE not found — something is wrong with the install"
    exit 1
  fi
fi

MISSING=$(python3 -c "
import re, sys, yaml
manifest = yaml.safe_load(open('distribution.yaml'))
required = [v['name'] for v in manifest.get('env_requires', []) if v.get('required')]
values = {}
with open('$ENV_FILE') as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, _, v = line.partition('=')
        values[k.strip()] = v.strip()
missing = [name for name in required if not values.get(name)]
print(' '.join(missing))
")

if [ -n "$MISSING" ]; then
  fail "$ENV_FILE is missing values for: $MISSING"
  info ""
  info "Fill those in, then re-run this script:"
  info "  \$EDITOR $ENV_FILE"
  info "  ./scripts/install.sh $PROFILE"
  exit 0
fi

LLM_PROVIDER=$(python3 -c "
values = {}
with open('$ENV_FILE') as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, _, v = line.partition('=')
        values[k.strip()] = v.strip()
print('anthropic' if values.get('ANTHROPIC_API_KEY') else 'copilot' if values.get('COPILOT_GITHUB_TOKEN') else '')
")

if [ -z "$LLM_PROVIDER" ]; then
  fail "$ENV_FILE has no model provider — set ONE of ANTHROPIC_API_KEY or COPILOT_GITHUB_TOKEN"
  info ""
  info "Fill one in, then re-run this script:"
  info "  \$EDITOR $ENV_FILE"
  info "  ./scripts/install.sh $PROFILE"
  exit 0
fi
pass "all required credentials are filled in ($ENV_FILE)"

# Profile updates reset config.yaml to the Anthropic default, so re-pin the
# provider here on every run.
if [ "$LLM_PROVIDER" = "copilot" ]; then
  hermes -p "$PROFILE" config set model.provider copilot >/dev/null 2>&1 \
    && hermes -p "$PROFILE" config set model.default claude-sonnet-4.6 >/dev/null 2>&1 \
    && pass "model provider: GitHub Copilot (claude-sonnet-4.6)" \
    || fail "couldn't set the Copilot provider — run: hermes -p $PROFILE config set model.provider copilot"
else
  pass "model provider: Anthropic (claude-sonnet-4-6)"
fi

# Hermes only substitutes ${HERMES_SKILL_DIR}/${HERMES_SESSION_ID} in SKILL.md
# content — ${KYVERNO_REPO} etc. are never resolved by Hermes itself, so the
# model would otherwise read that literal placeholder text. Do it ourselves.
python3 -c "
import glob
values = {}
with open('$ENV_FILE') as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, _, v = line.partition('=')
        values[k.strip()] = v.strip()
for var in ('KYVERNO_REPO', 'MAINTAINER_GITHUB_LOGIN', 'SLACK_HOME_CHANNEL'):
    val = values.get(var)
    if not val:
        continue
    token = '\${' + var + '}'
    for path in glob.glob('$PROFILE_DIR/skills/*/SKILL.md'):
        text = open(path).read()
        if token in text:
            open(path, 'w').write(text.replace(token, val))
"
pass "skill instructions resolved to real env values"

step "4. AGENTS.md cache"

# Discovers every AGENTS.md/ARCHITECTURE.md in the repo (not just api/AGENTS.md — kyverno/kyverno
# has one per major package: pkg/engine, pkg/cel, pkg/webhooks, etc., plus root AGENTS.md and
# ARCHITECTURE.md) via one git-tree call, then caches each as its own mnemosyne entry so
# kyverno-context can recall the one relevant to whatever package is in play instead of a fresh
# search_code every session.
AGENTS_SEED_FILE="$(mktemp)"
python3 -c "
import base64, json, ssl, urllib.request, urllib.error

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = None  # falls back to the interpreter's default cert store

values = {}
with open('$ENV_FILE') as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, _, v = line.partition('=')
        values[k.strip()] = v.strip()

repo = values.get('KYVERNO_REPO')
token = values.get('GITHUB_TOKEN')

def api_get(path):
    req = urllib.request.Request(
        f'https://api.github.com/{path}',
        headers={
            'Authorization': f'Bearer {token}',
            'Accept': 'application/vnd.github+json',
            'User-Agent': 'kyverno-assistant-install',
        },
    )
    with urllib.request.urlopen(req, timeout=20, context=_SSL_CTX) as resp:
        return json.load(resp)

try:
    default_branch = api_get(f'repos/{repo}')['default_branch']
    tree = api_get(f'repos/{repo}/git/trees/{default_branch}?recursive=true')
except (urllib.error.URLError, urllib.error.HTTPError, ssl.SSLError, KeyError) as exc:
    print(f'SKIP: could not list {repo}\'s tree: {exc}')
    print('HINT: if this is an SSL cert error, try: python3 -m pip install certifi')
    raise SystemExit(0)

import re
doc_paths = [n['path'] for n in tree.get('tree', [])
             if re.search(r'(?i)agents\.md$|architecture\.md$', n['path'])]
if not doc_paths:
    print('SKIP: no AGENTS.md/ARCHITECTURE.md files found')
    raise SystemExit(0)

entries = []
failed = []
for path in doc_paths:
    try:
        payload = api_get(f'repos/{repo}/contents/{path}')
        content = base64.b64decode(payload['content']).decode('utf-8')
    except (urllib.error.URLError, urllib.error.HTTPError, ssl.SSLError, KeyError) as exc:
        failed.append(path)
        continue
    entries.append({
        'id': f'kyverno-doc:{path}',
        'content': f'--- {path} ---\n{content}',
        'source': 'install-seed',
        'timestamp': '2026-01-01T00:00:00',
        'session_id': 'install-seed',
        'importance': 0.9,
        'scope': 'global',
        'pinned': 1,
    })

if not entries:
    print('SKIP: found doc paths but could not fetch any of them')
    raise SystemExit(0)

seed = {'mnemosyne_export': {'version': '1.3'}, 'working_memory': entries}
with open('$AGENTS_SEED_FILE', 'w') as f:
    json.dump(seed, f)
print(f'OK: {len(entries)} cached' + (f', {len(failed)} failed: {failed}' if failed else ''))
" > "$AGENTS_SEED_FILE.status" 2>&1

if grep -q "^OK:" "$AGENTS_SEED_FILE.status"; then
  if hermes -p "$PROFILE" mnemosyne import -i "$AGENTS_SEED_FILE" --force >/dev/null 2>&1; then
    pass "$(sed 's/^OK: //' "$AGENTS_SEED_FILE.status") (recall by 'kyverno-doc:<path>' any session)"
  else
    info "docs fetched but mnemosyne import failed — run: hermes -p $PROFILE mnemosyne import -i $AGENTS_SEED_FILE --force"
  fi
else
  info "$(cat "$AGENTS_SEED_FILE.status") — skipping cache, kyverno-context will fall back to search_code"
fi
rm -f "$AGENTS_SEED_FILE" "$AGENTS_SEED_FILE.status"

SLACK_CONFIGURED=$(python3 -c "
values = {}
with open('$ENV_FILE') as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, _, v = line.partition('=')
        values[k.strip()] = v.strip()
print('yes' if values.get('SLACK_BOT_TOKEN') and values.get('SLACK_APP_TOKEN') else 'no')
")

step "5. Messaging gateway"

if [ "$SLACK_CONFIGURED" = "yes" ]; then
  # gateway install/restart only work against the 'default' profile — switch
  # to it, then switch back, so this script doesn't silently change which
  # profile is sticky-active for the maintainer's own `hermes chat`.
  ORIGINAL_ACTIVE=$(hermes profile list 2>/dev/null | awk '$1 ~ /◆/ {gsub(/◆/,"",$1); print $1; exit}')
  hermes profile use default >/dev/null 2>&1
  GATEWAY_OUT=$(hermes gateway install 2>&1)
  if echo "$GATEWAY_OUT" | grep -qi "already installed"; then
    pass "gateway service already installed"
    info "if the bot doesn't respond, it may need: hermes gateway restart"
  elif echo "$GATEWAY_OUT" | grep -qi "install"; then
    pass "gateway service installed"
  else
    fail "gateway install had an unexpected result — run: hermes gateway install"
    info "$GATEWAY_OUT"
  fi
  if [ -n "$ORIGINAL_ACTIVE" ] && [ "$ORIGINAL_ACTIVE" != "default" ]; then
    hermes profile use "$ORIGINAL_ACTIVE" >/dev/null 2>&1
  fi
else
  info "no Slack credentials set — skipping gateway (CLI-only use is fine)"
fi

step "6. Sanity checks"

MCP_OUT=$(hermes -p "$PROFILE" mcp list 2>&1)
if echo "$MCP_OUT" | grep -q "github .*enabled"; then
  pass "github MCP server enabled"
else
  fail "github MCP server not enabled — run: hermes -p $PROFILE mcp list"
fi

if [ "$SLACK_CONFIGURED" = "yes" ]; then
  if echo "$MCP_OUT" | grep -q "slack .*enabled"; then
    pass "slack MCP server enabled"
  else
    fail "slack MCP server not enabled — run: hermes -p $PROFILE mcp list"
  fi
fi

if hermes -p "$PROFILE" mcp test github >/dev/null 2>&1; then
  pass "github MCP server reachable (this doesn't verify the token itself — ask it a real question to confirm)"
else
  fail "github MCP server check failed — run: hermes -p $PROFILE mcp test github"
fi

if [ "$SLACK_CONFIGURED" = "yes" ]; then
  if hermes -p "$PROFILE" mcp test slack >/dev/null 2>&1; then
    pass "slack tokens work"
  else
    fail "slack connection failed — check SLACK_BOT_TOKEN/SLACK_APP_TOKEN, then: hermes -p $PROFILE mcp test slack"
  fi
fi

if hermes -p "$PROFILE" hooks doctor 2>&1 | grep -q "All shell hooks look healthy"; then
  pass "shell hooks healthy"
else
  info "shell hooks need approval on first real use — run: hermes -p $PROFILE hooks doctor"
fi

TOOLS_OUT=$(hermes -p "$PROFILE" tools list 2>&1)
LEAKED=$(echo "$TOOLS_OUT" | grep -E "✓ enabled  (terminal|file|browser|code_execution|computer_use|connections|delegation)  " || true)
if [ -z "$LEAKED" ]; then
  pass "no laptop-level tool access (terminal/file/browser/etc. disabled)"
else
  fail "unexpected tool access enabled — this profile can reach beyond GitHub/Slack:"
  info "$LEAKED"
fi

step "Done"

info "Talk to it: hermes -p $PROFILE chat  (or 'kyverno chat' if the alias took)"
info ""
info "Cron jobs ship paused — review before turning any on:"
info "  hermes -p $PROFILE cron list"
info "  hermes -p $PROFILE cron resume <job-id>"
