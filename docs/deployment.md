# Deployment — Phase 0 runbook

Order matters here: the webhook URL has to exist before the GitHub App can
be registered, and the App has to exist before it can be installed on a
repo. Each step lists what's already built vs. what's a manual action.

## 1. Prerequisites (manual)

- [ ] A **Socket.dev** account + API key (free tier): https://socket.dev
- [ ] A **dedicated sandbox GitHub repo** to test against (not
      `kyverno/kyverno`, not this repo). `gh repo create <name> --public`
      works if you want me to create it.
- [ ] Docker running locally (`docker --version` — confirmed available:
      28.3.2). `gh` CLI authenticated (confirmed: `suhaani-agarwal`).
      `ngrok` installed and already has an authtoken configured — use this
      instead of the plan's original `cloudflared` assumption, since it's
      already set up on this machine and ngrok's free tier includes one
      static domain (stable URL across restarts).

## 2. Bring Hermes up locally

```bash
cp .env.example .env
# fill in ANTHROPIC_API_KEY at minimum to start the gateway;
# the rest (GITHUB_*, KYCTRL_READONLY_GITHUB_TOKEN, SOCKET_DEV_API_KEY)
# are needed before the dependabot-pr route will work end to end, but
# aren't needed just to confirm the container starts.
./setup.sh
docker compose logs -f gateway   # confirm it starts and binds :8644
```

## 3. Expose :8644 publicly (before the App exists)

```bash
ngrok http --domain=<your-reserved-static-domain>.ngrok-free.app 8644
```

If you haven't reserved a static domain yet: https://dashboard.ngrok.com/domains
(free, one included). Without it, ngrok gives a random URL that changes
every restart — fine for a single test session, painful once you're
re-registering the App's webhook URL every time Hermes restarts. Note the
resulting `https://...ngrok-free.app` URL — it's the GitHub App's webhook
URL in the next step, and it's also what changes (App settings need a
one-line edit) once this moves to the Linode node.

## 4. Register the `@kyctrl-bot` GitHub App (manual, GitHub UI)

1. https://github.com/settings/apps/new (or your org's equivalent).
2. Webhook URL: the ngrok URL from step 3, path `/webhooks/dependabot-pr`
   (i.e. `https://<domain>/webhooks/dependabot-pr` — this is the top-level
   default-profile route path from `config.yaml`, not a `/p/<profile>/`
   path, since the webhook platform itself only lives on the default
   profile).
3. Webhook secret: generate one (`openssl rand -hex 32`), put it in `.env`
   as `GITHUB_WEBHOOK_SECRET`, enter the same value in the App form.
4. Permissions: Pull requests (Read & write), Issues (Read & write),
   Contents (Read-only), Checks (Read-only).
5. Subscribe to events: Pull request, Issue comment.
6. Create the App. Generate a private key, download the `.pem`, and save it
   as `.hermes-data/secrets/kyctrl-bot.pem` (matching `GITHUB_APP_PRIVATE_KEY_PATH`
   in `.env.example`, `/opt/data/secrets/kyctrl-bot.pem` from the
   container's side). `.hermes-data/` is Hermes's gitignored runtime data
   directory (see `docker-compose.yml`'s header comment) — `./setup.sh`
   syncs tracked config *into* it but never touches anything else there,
   so the key is safe to drop in and leave.
7. Note the App ID → `.env`'s `GITHUB_APP_ID`.

**Don't commit the `.pem`.** `.gitignore` already excludes `*.pem`, but
double-check `git status` before your first commit regardless — a leaked
App private key is a full-compromise-of-the-bot-identity event, not a
"rotate one token" event.

## 5. Get the comment-capable token

`KYCTRL_READONLY_GITHUB_TOKEN` (see `.env.example`'s comment on exact
scopes) is a separate fine-grained PAT, not the App's own credential —
create it at https://github.com/settings/personal-access-tokens/new,
scoped to the sandbox repo only, Contents: Read, Pull requests: Read,
Issues: Read & Write, Checks: Read.

## 6. Install the App + auto-request workflow on the sandbox repo

1. Install `@kyctrl-bot` on the sandbox repo (GitHub App's install page).
2. Copy `.github/workflows/copilot-auto-request.yml` and
   `kyctrl-auto-merge.yml` into the sandbox repo (Phase 0 targets a
   sandbox repo, so these workflows need to physically live there, not
   just in this kyctrl repo — this repo is Hermes's brain, the sandbox
   repo is where the workflows actually run).
3. Confirm the sandbox repo's plan supports `gh pr edit --add-reviewer
   @copilot` (Copilot code review availability varies by plan) — open any
   test PR and check the workflow run succeeds.

## 7. End-to-end test

Open a PR on the sandbox repo that mimics a Dependabot update (easiest:
let Dependabot itself open one — add a trivial `dependabot.yml` with a
`schedule: daily` for an ecosystem in `settings.yaml`'s
`auto_merge_ecosystems`, or manually craft a branch named
`dependabot/npm_and_yarn/<pkg>-<version>` with a commit message containing
the `updated-dependencies:` trailer block `scripts/dependabot-policy-engine.py`
parses).

Expect, within roughly 30 seconds:
1. The Copilot-review-request workflow runs.
2. A `@kyctrl-bot` comment appears with the verdict and reasons.
3. If APPROVE: `kyctrl-auto-merge.yml` fires and the PR is merged.

If nothing happens: `docker compose logs -f gateway` first — most Phase 0
failures are webhook delivery (check the App's "Recent Deliveries" tab for
the HTTP status Hermes returned) or the policy engine script erroring
before printing anything (a nonzero exit or exception makes Hermes treat
the event as ignored, per the `script` hook contract — same visible
behavior as a deliberate `[SILENT]`, so check logs, not just GitHub's UI).

## Known-unverified items to confirm on the first real run

- Socket.dev's `/purl` request/response shape and the ecosystem-name
  mapping in `get_socket_score()` — confirmed from docs search, not a live
  call. See `docs/architecture.md`'s "Known gaps".
- The exact `@kyctrl-bot` App login string used in `kyctrl-auto-merge.yml`'s
  trigger condition.

## Later: moving to Linode

Once Jim's Linode access lands: same `docker-compose.yml` runs there
unchanged (Linux natively supports `network_mode: host`, which also
unlocks the dashboard service — see the compose file's header comment for
what to change). Swap the App's webhook URL from the ngrok domain to the
Linode node's address, drop the ngrok tunnel. No code or config changes
beyond that URL.
