# Adding a new bot

`dependabot-bot` is the reference implementation — copy its pattern rather
than inventing a new one. Checklist, in order:

1. **`settings.yaml`**: flip the bot's `enabled: false` to `true` and fill
   in its real tunables next to the existing placeholder section.
2. **`scripts/<bot>-<thing>.py`** (if the bot has a deterministic decision
   to make — not every bot does): reads the webhook payload from stdin,
   reads `settings.yaml`, does the actual check, prints either `[SILENT]`
   or a JSON payload with a `kyctrl_verdict`-shaped key for the prompt to
   reference. `dependabot-policy-engine.py` is the template for the
   stdin/stdout contract and the "fail closed on any external API error"
   pattern.
3. **`skills/*.md`**: one file per distinct piece of domain knowledge the
   bot's comment-writing needs, written as context for the LLM (why a
   check exists, what a FLAG reason actually means), not as instructions
   changing what the bot is allowed to do — permissions live in
   `config.yaml`, not skills.
4. **If the bot touches a PR**: load `skills/copilot-review-check.md` and
   have its script check Copilot's review the same way
   `dependabot-policy-engine.py` does — this is a cross-cutting pattern,
   not something to reinvent per bot.
5. **`profiles/<bot>/SOUL.md`**: this bot's specific job, tone, and the
   explicit "you don't decide, you explain" framing.
6. **`profiles/<bot>/config.yaml`**: model settings only. No
   `platforms:` block — ever. Port-binding platforms live on the default
   profile's top-level `config.yaml` only.
7. **Top-level `config.yaml`**: uncomment/add the bot's route under
   `platforms.webhook.extra.routes`, add a `custom_toolsets` entry that is
   a hand-picked allowlist (never the raw `mcp-github` toolset — see
   `docs/architecture.md`'s security model), bind `profile:` to the new
   bot.
8. **If the bot needs a privileged action**: it doesn't get a tool for it.
   It posts a trigger comment; a new `.github/workflows/*.yml` (in the
   *target* repo, not necessarily this one) watches for that exact string
   and the bot's login, and runs with `GITHUB_TOKEN`. See
   `kyctrl-auto-merge.yml` for the pattern.
9. **Test against the sandbox repo** (see `docs/deployment.md`) before
   ever pointing a route at `kyverno/kyverno`.
