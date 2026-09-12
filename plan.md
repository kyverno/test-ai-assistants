# kyctrl — Planning Prompt for Claude Code

You are helping build **kyctrl**, an autonomous AI maintainer assistant for the Kyverno CNCF project. This is an empty repository in the Kyverno GitHub org. Your job right now is to **plan** the base architecture — not implement everything at once. Read this entire document before proposing anything.

---

## What kyctrl is

kyctrl is a bot system that automates the mechanical maintainer work on `kyverno/kyverno`: issue triage, Dependabot PR merges, bug reproduction, PR coaching, codebase Q&A, and weekly pattern detection. It runs as a set of specialised agents, each with a narrow toolset and no capability to take privileged actions (merge PRs, push code, run clusters) directly.

The system is built on:
- **Hermes Agent** (MIT, NousResearch) as the runtime: webhook server, bot profiles, cron, Slack gateway, memory
- **Claude API** (claude-sonnet-4-6) as the intelligence layer inside each bot — only for writing comments and explaining decisions, never for making binary decisions
- **CodeGraph** as the codebase understanding layer — AST-indexed symbol graph of the kyverno repo, served as an MCP server
- **GitHub Actions** as the only place privileged tokens live — merges, KinD cluster runs, and codegen all execute here
- **CodeRabbit** (we may switch our decision to github copilot instead later) (free for public OSS repos) for PR code review — kyctrl reads its output, does not replace it
- **Hookdeck** (free tier) sitting in front of Hermes to queue, validate HMAC, and deduplicate GitHub webhook deliveries

---

## The security model — this is the most important constraint

**The LLM never holds a token that can take a privileged action.**

- Hermes bots can read GitHub data and post comments. That is all.
- Merges happen when a GitHub Actions workflow sees a trigger comment (e.g. `/kyctrl-merge approved`) posted by `@kyctrl-bot` and runs `gh pr merge` using `GITHUB_TOKEN` — which exists only inside the Actions runner and never touches Hermes.
- KinD cluster reproduction happens when a GitHub Actions workflow sees `/kyctrl-reproduce version=... issue=...` and runs the cluster. Hermes never has `kubectl` or `helm` in its toolset.
- This is enforced architecturally: Hermes webhook routes have a `toolsets:` field that replaces the available tools for that route. A bot without `gh pr merge` in its toolset cannot call it — this is not a prompt instruction, it is what tools exist.

---

## The nine bots — each is a Hermes Profile

A Hermes Profile is a directory under `~/.hermes/profiles/<name>/` with its own SOUL.md (system prompt), config.yaml (model, toolset), skills (loaded markdown context files), and SQLite memory. All nine profiles share one Hermes process via profile multiplexing on a single port.

1. **triage-bot** — fires on `issues.opened`. Detects missing Kyverno fields (version, K8s version, policy YAML, resource YAML, actual vs expected). Runs issue lifecycle FSM (Python, hardcoded transitions). Posts missing-info requests. For complete reports, posts `/kyctrl-reproduce` trigger comment.

2. **dependabot-bot** (HAS TO BE BUILT FIRST FOR TESTING THIS APPROACH , MOST IMPORTANT) — fires on `pull_request.opened` from `dependabot[bot]`. Runs deterministic Python merge policy engine (reads signed git commit metadata via `ppkarwasz/fetch-metadata`, NOT the PR title which has a documented Dependabot bug; checks Socket.dev supply chain score; checks CI status). Posts `/kyctrl-merge approved` or a flag-for-human-review comment. Never merges itself.

3. **coach-bot** — fires on `pull_request.opened` from human contributors. Checks contributor memory (first-timer? DCO history?). Detects AI-generated PRs (5 signals). Codegen gate on `api/` changes. Reads CodeRabbit review and synthesises Kyverno-specific context for the contributor.

4. **reproduction-bot** — fires on comments containing `/kyctrl-reproduce`. Runs deterministic YAML extractor. Posts structured parameters for the GitHub Actions KinD workflow. Writes memory episodes on dispatch and completion.

5. **security-bot** — fires on `issues.labeled` where `label.name == "security"`. Has NO `gh issue comment` tool. Posts ONLY to private Slack channel. Pre-screens against CVEs and Kyverno dependency graph.

6. **pattern-bot** — cron, every Monday 09:00 IST. Reads all profiles' memory episodes from the past week. Clusters related issues. Files tracking issues. Opens skill-update PRs when maintainer override patterns cluster ≥3 times. Posts weekly digest to `#maintainers` Slack.

7. **qa-bot** — Slack `app_mention` and GitHub Discussions. Queries CodeGraph MCP for structural codebase answers. Citation enforcement: a Python closure tracks every source returned by CodeGraph per run; `propose_answer` rejects any citation not in that run's retrieval set — enforced in code, not prompt.

8. **flaky-bot** — cron twice daily + `workflow_run.completed` webhook. Tracks tests that fail across unrelated PRs. Files deduplicated tracking issues.

9. **merge-queue-bot** — fires on `pull_request.opened`, `pull_request.synchronize`, and `push` to main. Analyses which open PRs conflict (changed file overlap). Ranks PRs by CI status, CodeRabbit review status, recency, contributor history. Posts recommended merge order to `#maintainers` Slack. Read-only — never merges.

---

## The deterministic engines — no LLM in the decision path

Three Python scripts handle all binary decisions:

- **`dependabot-policy-engine.py`** — takes signed commit metadata, Socket.dev score, CI status, memory of regression history. Returns `APPROVE` or `FLAG: <reason>`. LLM receives this output and writes the comment.
- **`issue-fsm.py`** — hardcoded dict of valid state transitions (`needs-triage → needs-repro-info`, `needs-triage → repro-confirmed`, etc.). LLM writes the comment at each transition. LLM never decides which transitions are legal.
- **`yaml-extractor.py`** — deterministic parser for extracting policy and resource YAML from issue bodies. If extraction fails, posts a template request. LLM not involved.

---

## The GitHub Actions workflows — privileged execution

Three workflows live in `.github/workflows/` in the kyctrl repo (and will need to be in kyverno/kyverno eventually, but start here for testing):

- **`kyctrl-auto-merge.yml`** — triggers on `issue_comment.created` where body contains `/kyctrl-merge approved` and commenter is `@kyctrl-bot`. Runs `gh pr merge --squash` with `GITHUB_TOKEN`.
- **`kind-reproduction.yml`** — triggers on `issue_comment.created` where body contains `/kyctrl-reproduce` and commenter is `@kyctrl-bot`. Parses `version=`, `k8s=`, `issue=` parameters. Runs KinD cluster, installs Kyverno at exact version via Helm, applies extracted YAML manifests, captures output, posts results to the issue.
- **`codegen-check.yml`** — triggers on PRs touching `api/**`. Runs `make codegen-all-code && make verify-codegen`. Posts the exact diff and fix command if out of sync.

---

## The repo structure to build

```
kyctrl/  (this empty repo)
├── distribution.yaml          # Hermes Profile Distribution manifest
├── config.yaml                # Hermes: multiplex_profiles, all webhook routes, profile bindings
├── SOUL.md                    # Top-level kyctrl identity
├── mcp.json                   # CodeGraph MCP server config
│
├── profiles/
│   ├── triage-bot/
│   │   ├── SOUL.md
│   │   └── config.yaml        # model, toolset overrides
│   ├── dependabot-bot/SOUL.md
│   ├── coach-bot/SOUL.md
│   ├── reproduction-bot/SOUL.md
│   ├── security-bot/SOUL.md
│   ├── pattern-bot/SOUL.md
│   ├── qa-bot/SOUL.md
│   ├── flaky-bot/SOUL.md
│   └── merge-queue-bot/SOUL.md
│
├── skills/
│   ├── kyverno-triage.md
│   ├── issue-lifecycle-fsm.md
│   ├── kyverno-field-checklist.md
│   ├── dependabot-merge-policy.md
│   ├── supply-chain-risk.md
│   ├── kyverno-contributing.md
│   ├── dco-check.md
│   ├── codegen-requirements.md
│   ├── ai-slop-detector.md
│   ├── yaml-extraction.md
│   ├── kind-reproduction-workflow.md
│   ├── cve-cross-reference.md
│   ├── citation-enforcement.md
│   ├── clustering-protocol.md
│   ├── skill-update-protocol.md
│   ├── digest-template.md
│   ├── flaky-test-detection.md
│   ├── ci-structure.md
│   ├── conflict-prediction.md
│   └── pr-priority-ranking.md
│
├── scripts/
│   ├── dependabot-policy-engine.py
│   ├── issue-fsm.py
│   └── yaml-extractor.py
│
├── cron/
│   ├── pattern-bot-weekly.json
│   ├── flaky-bot-twice-daily.json
│   └── digest-weekly.json
│
├── .github/
│   └── workflows/
│       ├── kyctrl-auto-merge.yml
│       ├── kind-reproduction.yml
│       └── codegen-check.yml
│
├── docker-compose.yml         # Hermes + CodeGraph for local/VPS deployment
├── .env.example               # Required env vars with descriptions
├── setup.sh                   # One-command setup script
├── docs/
│   ├── architecture.md
│   ├── deployment.md
│   └── adding-a-new-bot.md
└── README.md
```

---

## Infrastructure context
(you need to tell me how this can actually happen and be run , i dont know how hermes will run here and how the application will run , we also require a SPA that does all the observability and auditing for everything kyctrl does with costs , reasoning, tools used, actions etc.)
- **VPS**: the Linode cluster Jim Bugwadia (mentor) is providing with public IPs. The Linode cluster has kubeconfig and credentials being sent. For initial testing, the Linode cluster is preferred because it's already set up.
- **Hermes runs on the VPS/Linode node** — one process, multiplexed, port `:8644`
- **CodeGraph runs as a sidecar** on the same node, port `:8765`, with kyverno repo cloned locally and re-indexed nightly
- **Hookdeck** is cloud (free tier) — sits in front of port `:8644`
- **GitHub App** (`@kyctrl-bot`) — needs to be registered to receive webhooks and act on kyverno repos
- **GitHub Actions** — runs for free on public repos

---

## What "plan" means here

Do NOT start writing code or files immediately. First:

1. **Read and confirm understanding.** Summarise the architecture in your own words: what runs where, what is deterministic, what uses the LLM, how privileged actions are separated.
RESEARCH.
2. **Identify what needs to exist before anything else.** Some things are blocked on others. For example: Hermes must be installable before profiles can be configured. The GitHub App must exist before webhooks can be received. The VPS/Linode must be configured before Hermes can run? CodeGraph needs the kyverno repo cloned before it can be indexed.

3. **Propose a phased build order.** The goal of Phase 0 is: Hermes running on the Linode node, one webhook received and routed to one profile, one comment posted back to a GitHub issue on this test repo. Everything else builds from there. Propose the phases clearly with what gets built in each and what the testable outcome of each phase is.

4. **Ask the questions you need answered before starting.** Some things you cannot know from this document:
   - Do we have Linode cluster access yet, or do we start with a local Docker setup?
   - Has the `@kyctrl-bot` GitHub App been registered yet?
   - Is Hookdeck set up or does that come later?
   - What is the test repo URL in the Kyverno GitHub org?
   - Are we installing Hermes via pip, or running it in Docker (the docker-compose path)?
   - Should the initial test bot be triage-bot (most complex) or a simpler one to validate the webhook pipeline first?

5. **Do not generate SOUL.md files, skill files, or scripts yet.** Those come after the infrastructure is confirmed working. The plan should specify what each file needs to contain, not write the content yet.

6. **Flag any gaps or risks.** Things to watch for:
   - Hermes `message_agent` A2A does not work in webhook-triggered sessions — the Triage → Reproduction Bot handoff uses trigger comments instead. Make sure this is reflected in the plan.
   - The `toolsets:` field on webhook routes is a manual config edit only — `hermes webhook subscribe` deliberately does not accept a toolsets flag. This means elevated tool grants require a config file change, not a CLI command. Good for security, but note it in the plan.
   - Per the Hermes multi-profile gateway docs: port-binding platforms (webhook, api_server) must be configured ONLY on the default profile. Secondary profiles are reachable via `/p/<profile>/webhooks/<route>` prefix. Do not configure webhook platform on individual bot profiles.
   - CodeRabbit is free for public repos with full Pro features permanently. Install it on the test repo first thing — it will be running before kyctrl is built and Coach Bot can start reading its output immediately.

---

## The first testable milestone

When Phase 0 is complete, this should work end to end:

1. Dependabot auto merging.

When Phase 1 is complete, this should work end to end:
1. Someone opens an issue on this test repo with a vague title ("ClusterPolicy not working") and no version, no YAML.
2. GitHub App webhook fires → Hookdeck queues and validates → Hermes receives on `:8644` → routes to `triage-bot` profile.
3. Triage Bot: loads `kyverno-triage.md` skill, runs `issue-fsm.py`, detects 4 missing fields, Claude writes the missing-info request, `gh issue comment` posts it, `gh issue edit` applies the `needs-repro-info` label.
4. The issue has a comment from `@kyctrl-bot` within 30 seconds of being filed. No maintainer touched it.

That is the proof of concept. Everything else — Dependabot Bot, reproduction, pattern detection, Q&A — builds from that foundation.

---

## Start here

Confirm you have read and understood the above. Then produce:
- A plain-English summary of the architecture (2–3 paragraphs)
- A list of questions you need answered before proposing the build order
- Once those are answered: a phased plan with clear phase names, what gets built, and what the testable outcome of each phase is

Do not write any files until the plan is confirmed.