# Deployment

kyverno-assistant is a Hermes profile distribution — there's no server to stand
up, no webhook receiver, no GitHub App to register. Install flow only.

## Install

```bash
hermes profile install github.com/kyverno/kyverno-assistant --name kyverno --alias -y
```

`--alias` takes no value — it creates a shell wrapper command named after
`--name` (or the manifest's own name if `--name` is omitted). `--alias
kyverno` is a common-looking but wrong invocation; it parses `kyverno` as a
second, unexpected positional argument and fails with "unrecognized
arguments."

(While this is still prototyped in this sandbox repo rather than published
separately, install from a local checkout instead: `hermes profile install .
--name kyverno --alias -y`.)

This prompts for the env vars listed in `distribution.yaml`'s `env_requires` and
writes them to the installed profile's `.env` (`~/.hermes/profiles/kyverno/.env`
— separate from this repo, never committed):

- `GITHUB_TOKEN` — fine-grained PAT: Contents Read, Pull requests Read & Write,
  Issues Read, Checks Read. Do **not** grant Contents Write or any merge/admin
  scope — the toolset doesn't call a merge endpoint, but the token shouldn't be
  able to either (belt and suspenders, see `docs/architecture.md`).
- `MAINTAINER_GITHUB_LOGIN` — the installing maintainer's GitHub username.
- `SLACK_BOT_TOKEN` (`xoxb-*`) / `SLACK_APP_TOKEN` (`xapp-*`, Socket Mode) — the
  Slack app's bot and app-level tokens. **Two different things use these** (see
  "Two separate Slack credential consumers" in `docs/architecture.md`):
  Hermes' own chat interface needs both, plus Socket Mode enabled and
  `app_mentions:read` + `message.channels` event subscriptions; the `slack`
  MCP server (reading/posting `SLACK_HOME_CHANNEL`) only ever uses
  `SLACK_BOT_TOKEN`, never `SLACK_APP_TOKEN`. Scopes needed either way:
  `chat:write`, `channels:history`, `channels:read`, `app_mentions:read`.
  Reinstall the app after subscribing to events. Note: the `slack` MCP
  server validates its token at process startup and exits immediately on an
  invalid one — a wrong/expired `SLACK_BOT_TOKEN` means that container never
  starts, not that it starts with reduced capability.
- `SLACK_ALLOWED_USERS` — the installing maintainer's Slack member ID (keeps
  this instance answering only them).
- `SLACK_HOME_CHANNEL` — the maintainers channel to read priority signals from
  and post the queue in. Invite the bot to it (`/invite @kyverno-assistant`).
- `KYVERNO_REPO` — `owner/repo` this instance manages. Defaults to
  `kyverno/test-ai-assistants` while prototyping; repoint at `kyverno/kyverno`
  once validated.
- `ANTHROPIC_API_KEY` — model provider key. Swap providers anytime with
  `hermes model`, no config changes needed.

## Run

```bash
kyverno chat
```

or talk to it in the configured Slack channel.

## Update

```bash
hermes profile update kyverno
```

Pulls the latest distribution version; the maintainer's own `.env`, memories,
and sessions are untouched.

## Validation plan

Before anything past v1 (see `docs/architecture.md`), validate end-to-end with
2-3 real maintainers on real PR queues — install, point at their actual repo,
confirm the queue reasoning (stacked PRs, generated-file conflicts, post-merge
CI risk) matches what they'd conclude by hand. Only after that is v2 (merge,
gated per the archived kyctrl pattern) worth building.

Before any of that: `skills/` still needs writing (see README status note),
and a real `hermes profile install .` has never been run against this repo.
When it is, confirm the registered toolset matches `docs/architecture.md`'s
"How the toolset allowlist is actually verified" section — the GitHub side of
that check can be repeated without any credentials by running the real
container and diffing its tool list:

```bash
docker run -i --rm \
  -e GITHUB_PERSONAL_ACCESS_TOKEN=dummy -e GITHUB_LOCKDOWN_MODE=1 \
  -e GITHUB_TOOLSETS=all -e GITHUB_EXCLUDE_TOOLS="$(python3 -c "import yaml;print(yaml.safe_load(open('config.yaml'))['mcp_servers']['github']['env']['GITHUB_EXCLUDE_TOOLS'])")" \
  ghcr.io/github/github-mcp-server
# then speak MCP `initialize` + `tools/list` over its stdio and compare
# against mcp_servers.github.tools.include in config.yaml.
```

The Slack side needs a real `SLACK_MCP_XOXB_TOKEN` first — the server exits
before the MCP handshake on an invalid one (see above), so this can't be
checked credential-free the way GitHub's can.
