# v3 plan

What to build after the current four skills (`kyverno-context`, `pr-queue`,
`pr-actions`, `discussions`) and two plugins (`kyverno-fetch`, `kyverno-sequencer`).
Every "verified" note below was checked against the real repo, API, or Hermes source
in 2026-10; anything unverified is marked as such and is the first task of its item.

## Where the project stands

| Layer | What exists |
|---|---|
| Install | `scripts/install.sh` — idempotent profile install/update, Anthropic **or** GitHub Copilot as the model provider, Slack gateway, sanity checks |
| Data | `fetch_pr_candidates` (one GraphQL pass per PR, concurrent): labels, files, CI, threads, CodeRabbit + Copilot verdicts, merge state, Dependabot bumps and semver level |
| Structure | `sequence_prs` — hard-edge graph (stacked, generated-file, body reference, closing-issue conflict), tiers, overlaps, e2e-gate state |
| Skills | `pr-queue` (merge sequence, review briefs, **Dependabot queue**), `pr-actions`, `discussions`, `kyverno-context` |
| Memory | built-in MEMORY/USER slots + Mnemosyne (incidents, rejections, contributor patterns) |
| Cron | review digest, memory sweep, memory consolidate — all ship paused |
| Safety | no merge tool (allowlist + token scope + fail-closed hook); no terminal/file/browser tools |

## Order of work

| # | Item | Size | Needs first |
|---|---|---|---|
| 1 | Dependabot queue — follow-ups | S–M | — |
| 2 | Maintainer-ownership signal (CODEOWNERS) | S | — |
| 3 | Security alerts and vulnerabilities | M | token-access test (below) |
| 4 | Semantic cross-PR analysis | L | a decision on where analysis runs (below) |
| 5 | Local dashboard | M | — |
| 6 | Gateway in Docker | M | the deployment-model decision in `to-do.md` |

---

## 1. Dependabot queue — follow-ups

**In place:** asking "which Dependabot PRs should I review or merge" runs
`pr-queue`'s "Procedure: Dependabot queue". It fetches every open Dependabot PR by
author (labels lag the triage sweep, which runs every two hours), reads each PR's
semver level, call sites, release notes, CI cause and Copilot findings, relates it to
sibling bumps and other open PRs, and gives one verdict per PR — merge now, fix first,
your review, wait, close/ignore — with timing. The maintainer does the merge.

**Next:**

- **Scheduled digest.** A fourth cron job, weekdays, posting only the *merge now* and
  *your review* groups with one line each. Ships paused like the others.
- **Alert-aware priority.** Security fixes already sort first when a PR carries
  `security` or names a `GHSA-`/`CVE-` ID. Item 3 adds severity from real alert data.
- **Real blast radius.** Call-site evidence is a text search of the default branch.
  Item 4's `govulncheck`/`go_symbol_references` replaces it with symbol-level
  reachability for the dependencies that matter (`k8s.io/*`, `github.com/kyverno/api`,
  anything under `pkg/engine`/`pkg/cel`).
- **Decision memory.** Persist "skip this major until X" per dependency
  (`mnemosyne_remember`) so a repeated Dependabot PR isn't re-litigated; the
  procedure already recalls it.

**Done when:** the digest runs for a week of real PRs and every "merge now" PR it named
merged without a follow-up revert.

## 2. Maintainer-ownership signal (CODEOWNERS)

**Gap:** `pr-queue` never asks whether a PR is the maintainer's to review, though
`kyverno-context` can resolve CODEOWNERS.

**Verified:** kyverno's CODEOWNERS opens with `* @kyverno/kyverno-core-maintainers`,
then path rules naming individuals (`/pkg/engine @eddycharly @realshuting
@MariamFahmy98 …`). GitHub requests every matching owner, so each open PR lists the
whole team plus the path owners as requested reviewers. Two consequences:

- Team membership alone is always true for a core maintainer, so it carries no signal.
  The signal is a *path-specific* rule that names the maintainer.
- `reviewRequests` shrinks as people review, so it can't be the source of truth.

**Approach:** compute ownership deterministically inside `kyverno-fetch`: read
`CODEOWNERS` once per call, apply last-match-wins to each PR's `changed_files`, resolve
team membership once (org Members read is already in the token's scopes), and return
`ownership` per PR — `direct` (a specific rule names the maintainer), `team-only`
(only the catch-all), or `none`. In `pr-queue`, `direct` ranks above `team-only` inside
a tier as a stated reason and is never a filter; `none` PRs are named, not hidden.

**Done when:** a maintainer who owns only `/pkg/cel` sees PRs touching it ranked as
theirs, with the matched rule cited.

## 3. Security alerts and vulnerabilities

**Gap:** `list_code_scanning_alerts`, `list_dependabot_alerts`,
`list_secret_scanning_alerts` and their `get_*` tools are granted but only the
Dependabot queue calls one.

**Verified:**

- With a non-collaborator token, `dependabot/alerts` and `code-scanning/alerts` return
  403 and `secret-scanning/alerts` returns 404 on `kyverno/kyverno`. **Unverified:**
  whether a core maintainer's token can read them. Test this first with a real
  maintainer token; the design below has a public-data path either way.
- Kyverno's disclosure policy (`kyverno/community` `SECURITY.md`): vulnerabilities in
  Kyverno are reported by email to `kyverno-security@googlegroups.com`, not as issues;
  a vulnerability in a dependency is reported to that project.
- `.coderabbit.yaml` already has a `kind/security` labeling instruction, a "Security
  label gate" pre-merge warning, and a root instruction to focus on security
  vulnerabilities. It reads the root `AGENTS.md` before every review.

**Approach — a `security` procedure in `pr-queue`:**

1. List open alerts by severity. If the token can't read them, query public advisory
   data per module@version (OSV or the Go vulnerability database) from a
   `kyverno-fetch`-style plugin tool; `go_vulncheck` (item 4) adds whether a vulnerable
   symbol is reachable from Kyverno's code.
2. For each alert, state criticality (severity × reachability), whether an open PR
   already fixes it (a Dependabot bump → *merge now*), and whether an open issue
   already tracks it.
3. Recommend by case:
   - **Public advisory, fix exists as a PR:** merge it; nothing to raise.
   - **Public advisory, no PR:** draft a tracking issue for the maintainer; the agent
     never creates one (`issue_write` is granted for labels only).
   - **A flaw in Kyverno's own code:** never a public issue, PR comment, or Slack
     post. Draft the email to `kyverno-security@googlegroups.com` for the maintainer
     to send.
   - **A flaw in another project:** point the maintainer to that project's own
     reporting channel.

**Upstream changes** (a PR to `kyverno/kyverno`, same route as the readiness
automation): a "Security-sensitive changes" section in root `AGENTS.md` (what counts,
the `kind/security` label, where to report), and CodeRabbit `path_instructions` for
`go.mod`/`go.sum` (flag new or bumped direct dependencies with a known advisory) and
`.github/workflows/**` (`pull_request_target`, widened `permissions`, unpinned
actions). One `AGENTS.md` edit reaches CodeRabbit and this assistant alike.

**Done when:** asking "what security issues are open" returns a severity-ordered list
with a verdict per item, and no unpatched Kyverno-code finding appears anywhere
public.

## 4. Semantic cross-PR analysis

**Gap:** the sequencer's edges are mechanical by design. Two PRs touching different
files can still depend on each other (a changed signature here, an unchanged caller
there), and nothing detects it.

**Verified tool landscape (Go, 2026-10):**

| Tool | Gives | Needs | Verdict |
|---|---|---|---|
| `gopls mcp` (built into gopls ≥ 0.20, stdio) | `go_symbol_references`, `go_package_api`, `go_search`, `go_diagnostics`, `go_vulncheck`, `go_workspace`, `go_rename_symbol` | Go toolchain, a checkout with deps resolved (`go mod download`, no build) | **Primary.** First-party, no third-party wrapper. No call-hierarchy tool — references only |
| `ast-grep` + `ast-grep-mcp` (active, MIT) | structural caller search | the binary; no Go setup | **Cheap baseline.** Name-based, no type resolution |
| `go-apidiff` (active) | exported-API breaks between two commits | deps resolved | **Per-PR gate.** Catches what generated-file ordering can't |
| `mcp-language-server` / `mcp-gopls` | gopls wrappers | same as gopls | Skip — `gopls mcp` replaces them (last push 2026-03 / 102 stars) |
| `scip-go` + `synaptic-scip`/`codegraph` | richest index | full Go build, custom glue | Skip for now |
| staticcheck, golangci-lint, difftastic, `go/callgraph`, GitHub's API | — | — | No cross-PR signal, or too heavy for kyverno's size |

**The decision this item needs:** the profile has no file or terminal tools by design,
and GitHub's `search_code` sees only the default branch, never a PR head. Analysis
therefore has to run *inside a plugin tool* (like `kyverno-fetch` making its own HTTP
calls), not through the model: a `kyverno-analyze` plugin keeps a bare clone, makes a
detached worktree for `refs/pull/N/head`, runs the tools in subprocesses with
timeouts, and returns JSON. That keeps laptop-level tool access disabled. It needs Go
and `ast-grep` on the host, which `install.sh` checks as optional prerequisites.

**Approach:**

1. `kyverno-analyze` returns, per PR or pair: `go-apidiff` breaks (main → PR head),
   `ast-grep` callers of each changed or removed symbol, and `go_vulncheck` reachability
   for dependency bumps.
2. `sequence_prs` accepts a `semantic_overlaps` annotation — a soft edge like
   `package_overlaps`, never a hard order; the agent decides, as for every
   within-tier judgment.
3. Run on demand for a PR or a pair the structural report surfaced, not across every
   open branch.

**Done when:** a PR that removes an exported symbol another open PR calls is flagged
on that pair, with both file paths cited.

## 5. Local dashboard

**Verified (Hermes source and docs):**

- A dashboard plugin is `dashboard/manifest.json` plus a **plain JS IIFE** — no build
  step — against `window.__HERMES_PLUGIN_SDK__`; an optional `plugin_api.py` adds
  FastAPI routes under `/api/plugins/<name>/`.
- The dashboard discovers plugins from `~/.hermes/plugins/<name>/dashboard/` (user
  scope), **not** from a profile's own `plugins/` directory, so `hermes profile
  install` does not ship one. `install.sh` has to copy it.
- `plugin_api.py` runs inside the dashboard process with that process's privileges,
  behind the dashboard's auth gate. Keep the dashboard on `127.0.0.1`; Hermes' own
  docs warn against `--host 0.0.0.0` with untrusted plugins.

**Approach:** a `kyverno-dashboard` plugin whose backend routes import `kyverno-fetch`
and `sequence_prs` directly, so the data path is the one the skills use. Panels follow
`docs/change_plan.md`'s dashboard spec (session header, queue in tier order,
`workflow-approval-required`, per-PR brief, Discussions, session history), plus a
Dependabot panel grouped by verdict. State lives in Mnemosyne or a local JSON file in
the profile directory.

**Done when:** `hermes dashboard` shows the live queue and Dependabot panel from a
fresh `install.sh` run with no manual copy step.

## 6. Gateway in Docker

**Verified:** Hermes ships a `Dockerfile` and `docker-compose.yml` with a `gateway`
service (`gateway run`) and a `dashboard` service, `~/.hermes` mounted at `/opt/data`,
`network_mode: host`, s6-overlay as PID 1, dashboard bound to `127.0.0.1`. The compose
file mounts no Docker socket.

**The wrinkle:** our `github` and `slack` MCP servers are `docker run` commands.
Inside the Hermes container they would need the host's Docker socket, which is
root-equivalent on the host and contradicts this profile's safety model. Prefer
removing the need: build an image `FROM` Hermes' that adds the two MCP servers as
binaries and point `config.yaml`'s `command:` at them.

**Prerequisite:** one instance serving several maintainers means shared credentials or
a service account. That is the deployment-model decision in `to-do.md` (personal
instance, shared read-only bot, shared full-capability bot) — decide it before
building.

**Done when:** `docker compose up` on a Linux host brings up the gateway with both MCP
servers reachable and `hermes -p kyverno mcp test` green, no socket mounted.

---

## Tracked elsewhere

`to-do.md` holds the remaining operational items: a write-capable PAT for a Kyverno
member, the Slack app in the Kubernetes workspace and the maintainers channel, shared
memory (mem0) across maintainers, and an issues-triage skill.

## Already covered upstream

`kyverno/kyverno#17864` added the `stale`/`no-stale` labels and a daily stale-author
sweep, and moved Dependabot triage to a two-hourly sweep with a heading-based Copilot
approval match.
