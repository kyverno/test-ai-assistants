# v2 plan: intelligent merge-sequencing

Written to be read cold, in a fresh session with no memory of how it was
produced. If you're picking this up: read "What's already built" first,
then "Before you implement anything" (this repeatedly cost real time to
learn the hard way — don't skip it), then the phases.

## What's already built (v1 — working, committed)

- **Permission model** (`config.yaml`): three independent, empirically
  verified layers enforcing "no merge tool, ever" — server-side
  `GITHUB_EXCLUDE_TOOLS` (github-mcp-server's own `--exclude-tools`,
  tested by running the real container and diffing its `tools/list`),
  Hermes-side `tools.include` (per-server allowlist), and a
  `hooks/block-dangerous-tools.sh` pre_tool_call hook (python3, reads
  `tool_name` from the real stdin JSON shape, blocks anything matching
  `merge|delete_repo|force_push`, `fail_closed: true`). Exactly 30 GitHub
  tools + 2 Slack tools granted right now. Full reasoning and how each
  layer was verified: `docs/architecture.md`.
- **Three skills**, domain-split (not pipeline-stage — see "Skill
  structure" below for why that matters going in):
  - `skills/kyverno-context/SKILL.md` — live-resolves labels/CODEOWNERS
    every session (never hardcoded), holds fixed facts about
    `kyverno/kyverno`'s real codegen fan-out (`api/**`) and pre-/post-merge
    CI split, can `search_code` on demand for repo docs.
  - `skills/pr-queue/SKILL.md` — fetches PRs (currently via
    `review-requested:`, **changing to `label:ready-for-review` in Phase
    1 below**), ranks with cited reasoning, answers open-ended questions,
    cross-references closing issues.
  - `skills/pr-actions/SKILL.md` — label/comment/review/branch-update via
    the maintainer's own token. Cannot merge, cannot true-rebase (only a
    branch-update/merge-commit is possible via GitHub's API — no tool
    here rewrites history).
- **A fake test environment on the real (public) `kyverno/test-ai-assistants`
  repo** — CODEOWNERS with 3 specificity levels, `api/` + `check-codegen.yaml`/
  `check-tests.yaml` path-mirroring scaffolding, ~9 test PRs + 2 test
  issues covering generated-file-conflict, stacked-PR, package-overlap,
  post-merge-risk (an honesty test — no path-to-suite mapping exists yet),
  duplicate-closing-issue, and unlinked-related-issue scenarios. Full
  list with PR numbers: `docs/test-scenarios.md`. One hard limitation:
  GitHub blocks self-review-requests, so all these test PRs are invisible
  to `review-requested:` queries — test by PR number, not "what's my
  queue," until Phase 1 switches the candidate query to a label (which
  self-authored PRs *can* carry).
- **Real Hermes CLI installed and used for live verification** (not just
  doc-reading) throughout — `hermes profile install`, `hermes mcp test`,
  `hermes mcp list`, `hermes hooks list/doctor/test` all confirmed the
  config behaves as designed. `docs/capabilities.md` is the plain-language
  "what it can actually do" writeup from a real session.

## Before you implement anything

**This project's single hardest-won lesson: verify against the real
running system, never trust a doc summary or an external document at face
value.** Multiple times, a first-pass answer from a documentation
summarizer turned out subtly wrong and was only caught by running the real
thing. Concretely, before touching code:

1. **Check whether [kyverno/kyverno#17698](https://github.com/kyverno/kyverno/pull/17698)
   has merged.** This PR (the user's own, from `suhaani-agarwal/kyverno`)
   adds the real `ready-for-review`/`needs-author-action` (human PRs) and
   `needs-review`/`major-bump` (Dependabot PRs) labelling automation this
   entire v2 plan is built around, plus a large real `area/*`/`kind/*`
   label taxonomy and `.coderabbit.yaml`/Copilot config. If merged, re-read
   the actual files on `main`, not this doc's summary of them — they may
   have changed during review. If still open, re-fetch from
   `suhaani-agarwal/kyverno@ci/ai-review-automation` (or wherever it's
   moved to) the same way, and build/test against that.
2. **Re-verify any new `config.yaml` tool grant with a live probe**, the
   same way every existing tool was verified this session:
   ```bash
   docker run -i --rm \
     -e GITHUB_PERSONAL_ACCESS_TOKEN=dummy -e GITHUB_LOCKDOWN_MODE=1 \
     -e GITHUB_TOOLSETS=all -e GITHUB_EXCLUDE_TOOLS="<current string>" \
     ghcr.io/github/github-mcp-server
   ```
   speaking MCP (`initialize` + `tools/list`) over its stdio, and diff the
   returned tool names against `tools.include` — they must match exactly.
   Recompute `GITHUB_EXCLUDE_TOOLS` as the exact complement (full
   `GITHUB_TOOLSETS=all` tool list minus `tools.include`) whenever
   `tools.include` changes; never let them drift out of being exact
   complements. Then re-confirm end to end through the real Hermes CLI:
   `hermes profile install . --name <profile> --force -y` then
   `hermes mcp test github` / `hermes mcp list`.
3. **Specific unverified claims this plan depends on — check these before
   trusting them, don't assume they resolved the way expected:**
   - `search_issues` + `issue_read(get)` as a reverse path to milestone
     linkage (working around `closingIssuesReferences` being GraphQL-only
     and not found on `pull_request_read`'s REST-shaped schema).
   - Whether `pull_request_read`'s `get_review_comments` method exposes
     thread-resolved state at all (GitHub's GraphQL
     `PullRequestReviewThread.isResolved` vs. what the REST-shaped tool
     actually returns).
   - Whether `search_issues` supports a `milestone:"name"` qualifier the
     same way `search_pull_requests` does — check GitHub's real search
     docs for the issue-search variant specifically.
   - `conversations_add_message`'s `thread_ts` parameter (threaded Slack
     replies) — found via source-level search this session, not yet
     confirmed against the tool's live schema (no valid, fully-scoped
     Slack token was available). Needs a real `SLACK_MCP_XOXB_TOKEN` with
     `channels:read` (a prior token was missing this scope and made the
     whole server crash at startup — see `docs/architecture.md`'s Slack
     section for why that's a hard-exit, not a soft failure).
4. **Two decisions the user has not yet made — don't pick for them:**
   - **Phase 3 (session cache):** no persistent cache vs. a JSON-file
     cache via the `file` toolset vs. SQLite via `code_execution`. Each
     option's tradeoffs are laid out in Phase 3 below.
   - **Phase 6 (merge queue):** stop at recommending a sequence and let
     the maintainer click "add to queue" themselves (Option A) vs. build
     a custom tool toward actually enqueueing (Option B, which means
     accepting that GitHub then merges autonomously once checks pass —
     a real change to this project's founding "human executes every
     sensitive action" invariant, not a technicality).
5. **Two things already decided — don't relitigate:**
   - Tool scope stays at today's ~32-tool allowlist. "Open-ended" (as the
     user specified it) means flexible reasoning over fixed tools, not a
     broader grant. Any genuinely new need gets exactly one new tool,
     verified the same way as everything else — never a preemptive
     widening.
   - Slack is on-demand and scoped to whatever PR is actually being
     discussed — never bulk-ingested (no "fetch last 200 messages at
     session start," no cron sweep). This was an explicit correction to
     the external architecture pitch that first suggested bulk ingestion.
6. **Code-graph (gopls-based semantic conflict detection) — recommended
   against, not merely deferred.** The reasoning (real cost is a synced
   local git clone + nontrivial cross-branch comparison logic, not
   "deploying a service" — `gopls mcp` spawns as a subprocess exactly like
   the existing GitHub/Slack MCP servers) is in Phase 5 below. Don't build
   it speculatively; only revisit if real usage shows the file-path-based
   risk classification actually misses conflicts often enough to matter.

## Skill structure: keep the domain split

Don't switch to a pipeline-stage split (`kyverno-bootstrap`/
`kyverno-sequence`/`kyverno-review`, from the external pitch) until Phase 3
(persistent cache) is chosen and built — that split is only justified once
there's an actual store for bootstrap to build and sequence/review to read
from. Until then, extend the existing three skills:

- `pr-queue` gains merge-sequencing (Phase 1) and review-brief assembly
  (Phase 2, including the Slack on-demand lookup from Phase 4).
- `kyverno-context` gains the file-risk classification vocabulary
  (generated/interface/test-only) and the `e2e-gate` fact.
- `pr-actions` stays exactly as narrow as it is — no analysis logic, ever.

## Phase 1 — Merge-sequence recommendation (buildable now, no new toolset)

**What kyverno/kyverno#17698 actually does** (read directly from the real
workflow YAML on the PR's branch, not just its description — re-verify
per step 1 above before trusting this section, since the PR may still
change before merging):

- `pr-readiness-check.yaml`: an 8-hourly + on-demand sweep. For every
  open, non-draft, human PR that *closes* (GitHub closing-keyword linking,
  checked via GraphQL `closingIssuesReferences`) an issue carrying an open
  `Kyverno Release ...` milestone: checks DCO, all other required checks,
  the `merge-conflicts` label, and any unresolved review thread whose last
  comment isn't from the author. Clean → `ready-for-review` (clears
  `needs-author-action`). A real finding → `needs-author-action` (clears
  `ready-for-review`) plus a one-time itemized comment. Pending/unclear →
  neither label asserted.
- `dependabot-merge-triage.yaml`: the Dependabot equivalent. Parses every
  commit's `updated-dependencies:` block (not just the tip — a rebase can
  move it) for semver level, promoting to the highest across a grouped
  bump, falling to `unknown` rather than silently inheriting a level.
  Combined with Copilot's approval + CI/conflict state →
  `ready-for-review` (confirmed patch/minor, clean, approved),
  `needs-review` (not clean or not approved), or `major-bump` +
  `needs-review` (major or unconfirmed level).
- New labels (`.github/labels.yml`): `ready-for-review` (0E8A16),
  `needs-author-action` (B60205), `needs-review` (FBCA04), `major-bump`
  (5319E7, permanent/informational, always paired with `needs-review`),
  plus `ai-generated` (CodeRabbit slop-detection) and `spam`. A large
  precise `area/*`/`kind/*` taxonomy also ships here — real ground truth
  for what Kyverno's labels look like, but `kyverno-context` still
  resolves labels live every session; this is context, not a hardcode
  shortcut.
- `.coderabbit.yaml`: CodeRabbit's job is explicitly security/lint/tests/
  CI/codegen — not logic or architecture — including an `error`-severity
  check that a type change under `api/**/*_types.go` came with its
  generated file updated (a single-PR, diff-level version of what
  `kyverno-context`'s codegen fact already covers cross-PR). Copilot's job
  is the complement: logic correctness, cross-file impact, architecture,
  `api/**` versioning rules. Use this real division when synthesizing
  "did Copilot/CodeRabbit review this" — they check different things, not
  the same thing twice.
- `e2e-gate.yaml` — **already live on `kyverno/kyverno` main today**, not
  part of #17698, previously unknown before this plan was written. Blocks
  further merges to a branch once post-merge tests fail on it
  (`e2e-failure` label) until fixed or bypassed (`e2e-gate-bypass`).
  Refines (doesn't replace) `kyverno-context`'s existing "nothing catches
  a bad interaction between two green PRs before both land" fact: true for
  the *first* bad interaction; post-merge failures *do* reactively block
  further merges. Add as a new Reference entry in `kyverno-context`.

**What to build:** candidate set = `label:ready-for-review` (not
`review-requested:` — the real workflow already gates CI/DCO/conflicts/
threads, so don't recompute that). One parallel fetch of every candidate's
changed files (Hermes genuinely executes concurrent tool calls from one
model turn — confirmed against Hermes' own changelog, no new
infrastructure needed, just emit the calls together). Build a file-overlap
conflict graph, risk-classify (generated > interface > test-only file
patterns), topologically sort (input-before-output for generated-file
pairs, definer-before-implementer for interface pairs, flag cycles for a
human), then reorder unconstrained tiers by milestone-alignment (closes
the milestone issue directly > closes an issue the milestone issue
references > age as tiebreaker). Every position gets a citable one-line
reason. Dependabot PRs carrying `needs-review`/`major-bump` surface as a
separate, explicitly-flagged set, not folded silently into the main
sequence.

**Also deepen "explain PR #N"** while touching `pr-queue`: what it
actually changes (plain-language purpose, not a diff dump), why (the
issue it closes), and what else it relates to (other open PRs/issues in
the same area, and this project's own current work when relevant — e.g.
asked about #17698 itself, it should recognize that as the readiness
infrastructure this plan depends on). Keep this depth-on-demand: the
default brief stays short and cheap; deeper cross-referencing triggers
only when asked for it.

**Files:** `skills/pr-queue/SKILL.md`, `skills/kyverno-context/SKILL.md`,
`config.yaml` (audit only — likely no new tools needed, see verification
list above), `docs/architecture.md` (replace the old "no such gate exists"
section — see git history for what that said), `docs/test-scenarios.md`
(mirror the real labels onto the sandbox repo, add a milestone-alignment
and a Dependabot `major-bump` scenario).

**Confirmed: this phase's quality is fully independent of Phase 6.** The
minimum-effort/minimum-rebase property comes entirely from the
topological sort here — merge-queue only changes who mechanically executes
a merge once a good order exists.

## Phase 2 — Review-brief assembly (no new toolset)

On a PR number: closes-issue, changed files, plain-language summary,
Copilot/CodeRabbit synthesis (lane-separated per the real division above),
review-thread state, risk, suggested action — live per-question, no cache.
Fold in Slack on-demand lookup here too (Phase 4, below — it's small
enough to not need its own skill file). Document the re-fetch-per-question
cost explicitly in `docs/capabilities.md` — that's the tradeoff Phase 3
would remove.

**Verify:** the 2 granted Slack tools (`conversations_history`,
`conversations_add_message`) actually support searching history for a
specific PR mention.

## Phase 3 — Persistent session cache (GATED — user decision required)

Three options — do not pick one, ask:

- **3a. No persistent cache.** Zero new toolset, zero new risk, every
  question re-fetches live.
- **3b. JSON-file cache via the `file` toolset.** First-ever widening
  beyond MCP-only tools. Verify what `file` actually exposes (scoped
  directory vs. whole filesystem) before trusting it.
- **3c. SQLite + `code_execution`** (the external pitch's exact design).
  The broadest capability grant this project would ever make. Somewhat
  de-risked by Hermes' own sandbox (confirmed this session: credentials
  are stripped from the execution environment; scripts can't recursively
  call MCP tools or `delegate_task`) — but that's not the same as
  "verified safe for this specific use." Probe the real sandbox
  boundaries (network access? filesystem scope? "project" vs "strict"
  mode difference?) against the real installed Hermes CLI before trusting
  it.

**Only once chosen:** `config.yaml` (toolset grant), new
`skills/kyverno-bootstrap/SKILL.md` + `kyverno-sequence/SKILL.md` +
`kyverno-review/SKILL.md` (the pipeline-stage split becomes justified
here), a cache-schema doc, a `cron/jobs.json` entry, a new
`docs/architecture.md` write-up matching the depth of the existing ones.

## Phase 4 — Slack: on-demand only (folds into Phase 2)

No bulk ingestion, no cron sweep, no standing Slack context loaded up
front — call `conversations_history` only when the maintainer is actively
reviewing/acting on a specific PR, or explicitly asks about Slack context.
New capability: when a review brief surfaces a PTAL thread, offer to draft
and post a reply via `conversations_add_message` with `thread_ts` set to
the original message (verify this parameter against the live schema
first — see "Before you implement" above). Draft, show the maintainer,
post only on confirmation.

## Phase 5 — Code-graph (v1.1, recommended against for now)

`gopls` (the Go team's own official language server) ships its own
built-in MCP server as of v0.20.0 (`gopls mcp`, stdio) — a better fit than
the external pitch's suggestions (a third-party semantic-search plugin, or
building a wrapper from scratch), and it does *not* require hosting a
persistent service — it spawns as a subprocess exactly like the existing
GitHub/Slack MCP servers. The real cost is elsewhere: it only reads local
saved files, so answering "does PR A's changed function have call-site
dependents in PR B's changed files" needs a synced local clone of
`KYVERNO_REPO`, checked out to a state containing *both* PRs'
changes simultaneously — nontrivial git-branch-manipulation logic, plus a
new sync-maintenance burden this profile has never carried. Weighed
against that: Phase 1's file-overlap graph plus generated/interface-file
risk classification already catches the large majority of real conflicts
in a Go monorepo via simple path matching. What code-graph adds beyond
that is narrower — a semantic conflict with *no* file overlap at all. Real,
but rarer, and not free to detect.

**Recommendation stands: don't build it.** Revisit only if real use shows
path-based risk classification misses conflicts often enough to matter —
an observable condition, not a hypothetical to build against pre-emptively.
If revisited: verify a live `gopls mcp` `tools/list` probe first (same
discipline as every other MCP server here), and confirm the available
gopls version actually supports it (v0.20.0+).

## Phase 6 — Merge-queue integration (GATED — user decision required)

GitHub's merge queue is real and distinct from direct merging (GraphQL
`enqueuePullRequest`/`dequeuePullRequest`, not the REST merge endpoint),
but `github-mcp-server` exposes **no merge-queue tool at all** today
(confirmed live against the real server's full 90-tool catalog this
session — re-check, since this could change in a future server version).
Building this means a brand-new custom MCP tool calling GitHub's GraphQL
API directly, needing the same three-layer verification discipline as
everything else here, from scratch.

More importantly: once enqueued, GitHub merges autonomously once checks
pass — no further human click. That's a different capability class from
every other action this profile takes, and a direct change to the "human
executes every sensitive action personally" invariant this whole project
was built around.

- **Option A:** Stop at recommending the sequence; the maintainer clicks
  "Add to merge queue" themselves. No new tool, ever, unless revisited.
- **Option B:** Build toward "recommend + human clicks enqueue" as a
  future custom tool, explicitly accepting autonomous post-enqueue merge.

Ask the user A vs. B before building either.

---

# Extension: discussions, memory, and security-advisory triage

Added after Phase 1-6 above were already planned and approved. Three new
capability areas, each researched against real tool schemas (live-probed
against the actual `github-mcp-server` container, same discipline as
everywhere else in this doc) before being written down — not assumed from
the request. One of them (Phase 10) is the single biggest capability grant
this project has ever considered and needs to be treated that way.

## Phase 7 — GitHub Discussions (small, low-risk addition)

**What:** answer contributor discussions when asked — read, and reply.

**Tools needed (currently excluded, confirmed via live schema probe):**
`list_discussion_categories`, `list_discussions`, `get_discussion`,
`get_discussion_comments`, `discussion_comment_write`. The last one is a
multiplexed tool with `method: add | reply | update | delete | mark_answer
| unmark_answer` — granting the tool grants all six methods; there is no
per-method permission split at the Hermes/server layer (confirmed against
its schema). Same pattern as `issue_write` already being broader than "just
labels" — restrict via skill instruction (only ever use `add`/`reply`
unless explicitly asked to do something else), not by pretending the tool
itself is narrower than it is.

**Files:** `config.yaml` (add these 5 tools to `tools.include`, recompute
`GITHUB_EXCLUDE_TOOLS` as the exact complement, re-verify live the same
way as every other tool here), a new `skills/discussions/SKILL.md` or fold
into `pr-actions` if small enough once written.

**Decision needed:** none — this is a normal, narrow, single-purpose
addition following the established process. Build it.

## Phase 8 — Persistent memory: build this, don't just gate it

**What Hermes' memory feature actually is** (read from the real feature
doc, not assumed): two per-profile files under
`~/.hermes/profiles/<name>/memories/` — `MEMORY.md` (the agent's own
environmental notes, ~2200 char limit) and `USER.md` (maintainer
preferences/working style, ~1375 char limit). Writes only happen via an
explicit `memory` tool call (`add`/`replace`/`remove`) — text like "I've
saved that" with no tool call persists nothing. Loaded as a frozen
snapshot at session start (~1300 tokens total, fixed cost, cache-friendly
— doesn't grow per-turn). Entries are scanned for injection/exfiltration
patterns before being accepted. User-inspectable (`cat`), reviewable
(`/memory pending`), approvable/rejectable, editable, deletable — not a
black box.

**This is exactly the tool for "know what the maintainer wants, how they
work, what sequence they work in."** `USER.md` is purpose-built for it.
Unlike Phase 3's cache options or Phase 10 below, this isn't a
categorically new kind of risk — it's a small, privacy-conscious,
already-auditable Hermes feature that happens to be unused right now.
Recommend building it, not gating it.

**Config needed:**
```yaml
memory:
  memory_enabled: true
  user_profile_enabled: true
```
plus granting the `memory` toolset (currently only `kyverno-assistant-tools`
is granted — this is a second, separate toolset to add to the `toolsets:`
list, verify it doesn't pull in anything beyond the `memory` tool itself).

**What to actually write to memory, concretely:** `USER.md` — the
maintainer's real review cadence and priorities as they're revealed in
conversation (e.g. "always wants stacked PRs called out even when not
asked," "treats Dependabot major-bumps as urgent," "prefers terse queue
summaries"). `MEMORY.md` — durable facts about the repo/environment this
agent keeps re-deriving that are actually stable (not the live-resolved
stuff like labels/CODEOWNERS, which must stay live per `kyverno-context`'s
existing rule — memory is for *this agent's own* operational notes, not a
cache of repo state). Also where the security-advisory triage log from
Phase 9 lives (see below) — this is what makes that phase a loop instead
of a one-off.

**Needs verification before trusting:** the exact `memory` tool's
call shape (add/replace/remove arguments) against a live Hermes session —
this session read the feature doc but never exercised the tool for real.

**Decision needed:** none, recommended to build directly.

## Phase 9 — Security-advisory triage (read + reasoning only, no new write risk)

**Scope, deliberately narrow for this phase:** analyze
`kyverno/kyverno`'s security advisories on request — explain what each
means, how critical, flag likely-redundant ones, recommend a fix approach.
**No PRs, no file edits, no branches in this phase** — that's Phase 10,
separated on purpose because it's a different risk class.

**Tools needed (confirmed via live schema probe):**
`list_repository_security_advisories` (filterable by `state`
triage/draft/published/closed and `sort` created/updated/published — this
single list call returns full advisory records; there is no separate
per-advisory `get` tool the way PRs have `pull_request_read` vs.
`list_pull_requests`, confirmed against the real schema, so don't build
around a `get_repository_security_advisory` tool that doesn't exist).
Already-granted alert tools (`list_code_scanning_alerts`,
`list_dependabot_alerts`, `list_secret_scanning_alerts` and their `get_*`
counterparts) are the *other* half of "security posture" — advisories are
GHSA-tracked, published vulnerability reports; alerts are live scanner
findings. Both matter, keep them conceptually distinct in the skill.

**Opening a tracking issue needs zero new tools** — `issue_write` (already
granted) has `method: "create"` in its real schema (confirmed this
session), not just `"update"`. `pr-actions`' current instruction ("only
ever pass `labels`") was written for the *queue-triage* use case and
doesn't apply here; a new skill (or a clearly-scoped addition to
`pr-actions`) should explicitly permit `issue_write(method="create", ...)`
for this specific purpose, stating why the broader method is allowed here
and nowhere else.

**Files:** new `skills/security-triage/SKILL.md` (analysis + tracking-issue
creation only), `config.yaml` (add `list_repository_security_advisories`
to `tools.include`, recompute the exclude complement, re-verify live),
`docs/architecture.md` (why advisories and alerts are handled by different
tools/skills).

**Decision needed:** none for this phase specifically — it's read-plus-
issue-creation, both low-risk, following the established process. Phase 10
(the actual fix) is where the real decision is.

## Phase 10 — Security fix PRs and instruction-file updates (GATED — the biggest decision in this plan)

**What's being asked:** the agent writes an actual code fix for a
vulnerability, opens a PR with it, and separately opens PRs updating
`kyverno/kyverno`'s own `AGENTS.md`/`.github/copilot-instructions.md`/
`.coderabbit.yaml` so the *existing* review pipeline (Copilot, CodeRabbit)
catches recurrences of that vulnerability class in future PRs without this
agent needing to catch it again — the "self-improving loop": the loop
isn't this agent getting smarter via training, it's this agent
externalizing what it learned into the instruction files that already
govern automated review, so the pipeline itself improves. Memory (Phase 8)
is where the record of *what was found and what was done about it* lives,
so the same advisory isn't re-triaged from scratch next time and the
maintainer can ask "what have you already flagged."

**Tools needed (confirmed via live schema probe, currently all
excluded):** `create_branch`, `create_or_update_file` (or `push_files` for
multi-file changes — same commit, one call, needs the target file's
current blob `sha` for updates, retrieved via already-granted
`get_file_contents`), `create_pull_request` (which also supports a
`reviewers` field — real GitHub usernames or `org/team-slug`, so the fix
PR can request review from a real Kyverno maintainer/team, not just this
profile's one maintainer).

**Why this is categorically different from everything else granted so
far:** every write this profile can currently make (label, comment, review
verdict, branch-update) operates on GitHub *metadata* — it cannot go
wrong in a way that ships a bug. Writing a security fix is *content* — a
wrong or incomplete fix can be worse than the original advisory (false
sense of safety, or a new bug introduced fixing the old one), and doing it
under an agent's own reasoning about a security vulnerability specifically
is close to the highest-stakes content-writing task there is. This is not
"one more tool to verify and add" — it's a different tier of decision.

**Recommended shape, if built at all — never autonomous:**
- Every PR created this way is a **draft PR** (`draft: true`, already a
  real parameter) with `reviewers` set to real Kyverno maintainers, never
  submitted as ready-for-merge by the agent itself.
- Requires the maintainer's **explicit, per-instance confirmation**
  ("yes, open the fix PR") — never triggered by a cron sweep on its own;
  a scheduled sweep's job (Phase 11) is to *notice and recommend*, not to
  write code unattended.
- **A new hook-level check**, not just a skill instruction: since Hermes
  hooks receive the real `tool_input` on stdin (confirmed this session —
  it's already part of the JSON wire protocol used by
  `hooks/block-dangerous-tools.sh`), a `pre_tool_call` hook can inspect
  `create_or_update_file`/`push_files`/`create_branch` calls' `path`/
  `branch` arguments and hard-block anything outside an explicit allowlist
  (e.g. only under specific known-safe paths, or only on branches
  prefixed `security-fix/`) — defense-in-depth for this specific new
  capability, the same layered-verification instinct used for merge.
  Design this hook and its allowlist before granting the tools, not after.
- The instruction-file-update PRs (`AGENTS.md`/Copilot/CodeRabbit config)
  are lower-risk than source-code fix PRs (they change review *guidance*,
  not shipped behavior) but use the exact same tools — worth considering
  whether to allow those with a lighter confirmation bar than actual
  source fixes, or hold both to the same bar for simplicity. Flagging as
  an open sub-decision, not resolving it here.

**Decision needed (yours, explicit):** build this at all, and if so, with
what confirmation/hook design — this is not something to greenlight by
default the way Phases 7-9 were. Given the stakes, treat this the same
way Phase 6 (merge-queue) was treated: present the tradeoff, wait for an
explicit answer, don't build toward it speculatively.

## Phase 11 — Scheduled/proactive operation (cron-triggered, notice-only)

**What:** a periodic (e.g. daily or weekly) Hermes cron job that runs
Phase 9's security-advisory triage unattended and, if it finds something
worth the maintainer's attention, posts a message to `SLACK_HOME_CHANNEL`
recommending a discussion — never silently opens a PR, never silently
edits a file. This is the "with a scheduled job" mode the user asked for,
scoped to *detection and notification*, with Phase 10's actual fix-writing
staying in the "after saying" (maintainer-confirmed) tier regardless of
how it was discovered.

**Mechanics (verified live, distinct from an earlier pass's guess at the
path):** Hermes cron jobs run in a completely fresh session each time.
Job definitions live per-profile, at `~/.hermes/profiles/<name>/cron/jobs.json`
— not a host-level path. A distribution ships new jobs via a `cron/jobs.json`
at the distribution repo's root (see this repo's own `cron/jobs.json` for
the review-digest job Phase 1's `pr-queue` already ships); `hermes profile
install`/`update` merges it into the installed profile's own file by job
`id`, arriving paused. The triage job needs Phase 8's memory to know what's
already been flagged (don't re-notify about the same advisory every run) —
this is the concrete link between Phase 8, 9, and 11 that makes the "loop"
real rather than three independent features. Posting uses the
already-granted `conversations_add_message` — no new Slack tool needed for
this phase. Delivery for a cron job specifically uses `--deliver`'s own
grammar (confirmed: a bare `slack` target resolves to the profile's
configured home channel via `hermes send`'s credential reuse, no running
gateway *listener* required for the send itself — though the gateway
process still has to be installed and running for the job's *schedule* to
tick at all, since the scheduler lives inside it).

**Files:** this repo's `cron/jobs.json`, `skills/security-triage/SKILL.md`
extended with a "when run unattended, never do more than notify" rule,
`docs/architecture.md` documenting this as the one place this profile
does anything without being asked, and exactly how far that goes (notice
+ Slack message, nothing else).

**Decision needed:** whether to build this at all is downstream of Phase
10's decision (there's limited point notifying about something the
maintainer has decided not to let the agent fix anyway) — revisit once
Phase 10 is resolved, not before.

## Summary addition — three more things needing your explicit call

4. **Phase 10 (security fix PRs):** build it at all, and if so, what
   confirmation/hook-allowlist design gates it. The single highest-stakes
   decision in this entire plan.
5. **Phase 10's instruction-file-update PRs specifically:** same
   confirmation bar as source-code fixes, or a lighter one, given they
   change review guidance rather than shipped behavior.
6. **Phase 11 (scheduled triage):** worth deciding only after Phase 10 is
   resolved — a notification about something the agent still can't act on
   without being asked is lower-value than once Phase 10 exists.
