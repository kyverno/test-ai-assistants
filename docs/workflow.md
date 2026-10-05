# Kyverno Maintainer Workflow — What the Agent Does

---

## The model

The agent eliminates mechanical work. The maintainer **decides**; the agent prepares, drafts, and executes. Every action on GitHub requires explicit maintainer confirmation — no silent writes, ever.

---

## Session open

1. Agent reads what happened last session — what was reviewed, what merged, what's waiting on authors, what was deferred, what issues were triaged.
2. Agent fetches what changed since then, named as real transitions, not a bare count — e.g. exactly which PRs moved `needs-author-action` → `ready-for-review`, which got a new CI result or review, which issues opened, gate status on any branch.
3. Agent surfaces any GitHub Discussion relevant to the current milestone or focus, unprompted — same as the standing GitHub Discussions capability below, just run proactively at session open instead of only on request.
4. Agent asks: **what's the focus today?**
   - A specific milestone
   - A specific author or area (package/directory)
   - Fork PRs needing workflow approval
   - Issue triage
   - A specific PR or issue number
   
   Agent does not default to all-PRs or oldest-first. No fetch happens until focus is set.

---

## PR work

### 1. Queue
Agent fetches all ready PRs matching the focus. Builds the dependency graph — which PRs must come before others (stacked branches, codegen ordering, explicit author dependencies, closing issue conflicts). Presents a tiered queue: PRs that are structurally free to review first, PRs that must wait for others to merge first. Within each tier, agent orders by its own judgment — using session context, maintainer history, what they said they want to get done today.

No maintainer action yet. Just orient — then **offer a guided walkthrough**: work through the queue in that order, one PR at a time (brief → decide → act → next), rather than only handing back a static list. Maintainer can accept, or jump straight to any PR by number instead.

### 2. Per PR — brief
Maintainer picks a PR, or agent recommends where to start. Agent presents:
- What the PR does, what files it touches, which subsystem
- Linked issue it closes, and every other open PR that also references or claims to close it (not just one — a second contributor can open a competing PR against the same issue without being assigned)
- CI status, CodeRabbit summary, unresolved review threads with direct links
- Key comments from the PR, any linked GitHub Discussion, and relevant Slack context — same context-gathering depth as the queue view, not a lighter version for a single PR
- Agent's recommendation: approve / request changes / defer / something else, and why
- **An offer to actually take that action.** On confirmation, the agent performs it in the same turn rather than waiting to be separately asked. On the deep-dive (maintainer asks to go deeper, or a risk signal warrants it), the offer widens to the agent's full action menu — approve, request changes, comment, apply a label, post a question in the linked Discussion or Slack about this PR, or act on the related issue (e.g. nudge a stalled author) — whichever are actually relevant here, not a recitation of every possible action regardless of fit.

### 3. Per PR — maintainer decides

| Decision | What happens |
|---|---|
| **Approve** | Agent posts approval via GitHub API. Marks done in dashboard with timestamp. |
| **Request changes** | Agent drafts the review comment incorporating maintainer's notes. Maintainer confirms or edits the draft. Agent posts it and applies `needs-author-action`, together, as one confirmed action. |
| **Commit a fix** | Agent confirms the exact fix content with the maintainer first, then commits it directly to the PR's own branch via the GitHub API. Still never a merge. |
| **Defer** | Agent records reason in memory. Marks deferred in dashboard. No GitHub action. |
| **Flag conflict** | Agent drafts a comment on the PR flagging the conflict (e.g. two PRs closing the same issue). Maintainer confirms. Agent posts it. |
| **Nudge the author** | PR is `needs-author-action` and stalled on something urgent (a severe linked issue, a near milestone). Agent drafts a nudge — a PR comment or a Slack message, whichever fits — maintainer confirms, agent posts it. A recommendation the agent raises proactively, not only on request. |
| **Apply e2e-gate-bypass** | Agent cannot do this on its own judgment — a deliberate human safety call, not a missing tool. Agent explains why it's needed and names the exact label. Maintainer applies it manually. |
| **Approve fork workflow run** | Agent cannot do this — no tool wraps this GitHub endpoint, and it exists specifically so a human looks at untrusted fork code before it runs with repo-secrets access. Agent links to the GitHub Actions approval page. Maintainer approves in browser. |

### 4. After approval — rebase cascade
If the just-approved PR has downstream PRs that will now need a rebase, agent proactively flags them: "PRs #X and #Y will need rebase now that #Z is approved. Want me to post a comment on those asking the authors to rebase?" Maintainer confirms. Agent posts the comments.

### 5. Next PR
Agent recommends the next PR in the queue. Maintainer can follow or jump to any PR by number.

---

## Issue work

### 1. Triage queue
Agent fetches new or unlabeled issues since last session. For each one, agent presents:
- Title, body summary, reporter
- Classification guess: bug / feature request / question / duplicate / out-of-scope
- If duplicate candidate: the likely original with a comparison
- **Every PR that references or claims to close this issue** — not just one. Any contributor can open a competing PR against an issue without being assigned to it, so more than one real candidate is a normal outcome, not an edge case; if more than one exists, flag it as possible duplicate effort rather than silently picking one.
- **A progress synthesis**, not a bare link list: given the PR(s) found, how far along is this issue toward resolution — e.g. "PR #X addresses this, currently `needs-author-action`, CI green" rather than just a link.
- Relevant GitHub Discussion and Slack context for this issue, checked with the same depth as a PR gets in the queue view — not a lighter pass just because it's an issue.
- Which subsystem it likely affects — stated as a guess with its basis (labels, file mentions in the body), or named plainly as unclear rather than fabricated.

### 2. Per issue — maintainer decides

| Decision | What happens |
|---|---|
| **Confirm as bug** | Agent applies `bug` label and milestone if specified. |
| **Confirm as feature request** | Agent applies `enhancement` label, optionally milestone. |
| **Mark duplicate** | Agent drafts closing comment: "Duplicate of #X — [one sentence why]." Maintainer confirms or edits. Agent posts it and closes the issue. |
| **Close as out-of-scope** | Agent drafts closing comment explaining why. Maintainer confirms or edits. Agent posts and closes. |
| **Needs more info** | Agent drafts comment asking for the specific missing information. Maintainer confirms or edits. Agent posts it and applies `needs-more-info` label. |
| **Assign to contributor** | Agent posts a comment tagging them and adds them as assignee. |
| **Add to milestone** | Agent applies the milestone to the issue. |
| **Nudge a stalled PR's author** | The issue's linked PR is `needs-author-action` and the issue reads as urgent. Agent drafts a nudge (PR comment or Slack message), maintainer confirms, agent posts it — raised proactively as part of the progress synthesis above, not only on request. |

### 3. Issue relationship surfacing
Always available as part of triage, and on request for the full sweep, agent surfaces the issue graph:
- Issues blocking other issues (detected from issue body text)
- Which issues are related to which PRs, and which PRs are related to which issues — the full graph, not a one-to-one mapping, since duplicate/competing PRs are expected
- Orphaned milestone issues — in the milestone, no linked PR, no assignee
- Issues where the closing PR was later reverted — still open in practice
- Cross-PR overlap — PRs in the queue that touch the same area as open issues
- Milestone health — how many open issues, how many have active PRs, rough velocity

### 4. Staleness housekeeping (on request)
Agent finds:
- `needs-more-info` issues where the reporter replied but the label wasn't removed
- Issues open a long time with no recent activity
- Issues where the reporter commented "fixed in vX" but the issue is still open

For each, agent drafts the closing comment. Maintainer bulk-confirms or skips individually. Agent executes.

---

## GitHub Discussions
Agent surfaces active discussions relevant to the current milestone or focus area, with links and summaries. Maintainer can ask the agent to go deeper on any discussion — full thread summary, key disagreements, current status, what decision (if any) is needed.

---

## Session close

1. Agent summarizes what happened: approvals posted, review comments sent, commits made, nudges sent, issues triaged, labels applied, deferred items with reasons.
2. Writes session summary to memory — available at the start of next session.
3. Updates dashboard: marks completed items with timestamp, updates deferred list, updates milestone health.
4. Flags follow-ups: PRs waiting on author response, issues waiting on more-info reply, PRs at risk of merge conflict.

---

## What the agent cannot do

- Merge PRs — hard block at token scope, never negotiable. This is the one write action that stays off-limits regardless of maintainer confirmation; everything else below — commenting, committing a fix, labeling, requesting changes, approving a review, posting a nudge — is allowed once confirmed.
- Apply `e2e-gate-bypass` — a deliberate human safety call, not a missing tool (the agent could mechanically apply the label the same way it applies any other). Agent suggests, maintainer applies manually.
- Approve workflow runs — no tool wraps GitHub's workflow-run-approval endpoint, and the gate exists specifically so a human looks at untrusted fork-PR code before it runs with repo-secrets access. Agent links to the page, maintainer approves in browser.
- Any GitHub write without the maintainer confirming the drafted action first

---

## Dashboard

The dashboard is a persistent page, one URL for the lifetime of the installation. The agent updates it during and between sessions. The maintainer has everything in one place with proper links.

It should be a page the maintainer actually wants to leave open — real visual design, not a bare table dump, and interactive: sortable/filterable panels, click through from a summary row into its detail panel.

**Session header**
Current date, milestone in focus, where things were left last session, quick status: ready PRs, gate status, PRs needing maintainer action, open issues vs milestone total.

**PR queue panel**
The latest queue, in tier order. Per PR: number + title linked to GitHub, tier, hard constraints if any, warnings, current real state, the agent's verdict/recommendation, and related items (overlaps, the issue it closes, any Discussion/Slack thread found) — every row carries this, not a reduced subset. PRs the maintainer acted on are marked with timestamp and what action was taken.

**Fork PRs needing workflow approval**
Separate section. Each linked to its GitHub PR and the Actions run awaiting approval.

**Per-PR detail panels** (added as maintainer dives in)
Full brief: file classification, changed files, linked issue, CI status, CodeRabbit summary, unresolved threads with links, key comments, any linked Discussion. What the agent recommended. What the maintainer decided.

**Issue panel**
Same shape as the PR panel: current state, triage classification and progress synthesis, every related PR (plural — duplicate/competing PRs included), related Discussion/Slack context, a real link. Plus milestone health — open issues, issues with active PRs, orphaned issues; triage queue — new issues since last session; relationship flags — duplicate candidates, blocked issue chains, reverted-closer issues, staleness flags.

**GitHub Discussions panel**
Active discussions relevant to the current milestone — what's actually being discussed, agent-summarized, not just a title list. Linked to GitHub, with status and what decision (if any) is pending.

**Session history**
What was reviewed, approved, deferred, triaged, closed last session. Links to everything touched.

---

## Build plan

Today, only PR-queue-building (the Queue/brief/Slack+Discussions-context parts of "PR work") is
built. Everything else above — Issue work, the dashboard, session open/close, the rebase
cascade, and most of the PR decide-table — is still to build. Four independently-shippable
phases, in this order:

### Findings this plan rests on (verified live, not assumed)

- **Probed the real `github-mcp-server` tool surface directly** (stdio `tools/list` against
  the real container, `GITHUB_TOOLSETS=all`, 90 tools returned). No tool anywhere wraps
  GitHub's workflow-run-approval or pending-deployment-review endpoints — "Approve fork
  workflow run: agent cannot do this" above is a real tool-coverage gap, not a policy choice,
  and stays link-only. `create_or_update_file`/`push_files`/`delete_file` do exist and are
  currently excluded — what "Commit a fix" above needs.
- **Asked directly about workflow-run approval** once it was clear it's a security gate (a
  human looking at untrusted fork code before it runs with repo-secrets access, not a
  correctness check) — kept link-only on purpose, not just because no tool exists.
- **Write-scope policy, decided this round**: a file-write tool is now in scope — commenting,
  committing, approving reviews, labeling, requesting changes all happen with maintainer
  confirmation. `merge_pull_request` is the one hard, non-negotiable block (token scope +
  allowlist + hook, three independent layers).
- **The real dashboard mechanism**, confirmed from a live first-party example
  (`~/.hermes/hermes-agent/plugins/kanban/`): a Hermes dashboard-plugin ships
  `dashboard/manifest.json` (name/label/icon/tab position/entry JS/css/api) plus a FastAPI
  backend, mounted at `/api/plugins/<name>/`, its own tab in `hermes dashboard`
  (`localhost:9119`) — not a claude.ai artifact, and not real-time push; it updates on skill
  action, the same as every panel in that real example.
- **No generic structured key-value/JSON store exists yet** in this project's memory layer —
  only Mnemosyne's id-keyed `remember`/`recall` and its 5-predicate triple store, neither a
  good fit for sortable dashboard state or a session-to-session diff snapshot. The dashboard
  plugin owns its own small local JSON state file instead.
- `plugins/kyverno-fetch/fetch.py`'s GraphQL/REST helpers (search → concurrent detail pass →
  cross-ref extraction/resolution, the `issueOrPullRequest` union lookup, the cross-reference
  regex) are directly reusable for an issue-side fetch — read, not assumed from the PR-side
  tool's shape.

### Phase 1 — Issue work (triage, actions, relationship graph, staleness)

No new tool grants needed — `issue_write`/`add_issue_comment`/`issue_read`/`search_issues`/
`list_issues` are already granted; `pr-actions` just self-restricts `issue_write` to `labels`
for PRs. Issues get their own skills with the broader fields.

- Extend `plugins/kyverno-fetch/fetch.py` with `fetch_issue_candidates(repo, search_query,
  limit)` — same template as `fetch_pr_candidates`, swapped to `is:issue`/`... on Issue`, plus
  an issue-relevant field set (`labels`, `assignees`, `milestone`, `comments`,
  `timelineItems` for revert/cross-ref detection — verify exact field names live first).
- New skill `skills/issue-triage/`: classification guess, the issue↔PR relationship graph
  (every PR that references or claims to close an issue, not just one — flags duplicate
  effort when more than one exists), the progress synthesis ("PR #X addresses this, currently
  `needs-author-action`, CI green"), the same Slack+Discussions context pass `pr-queue` does
  for PRs, the author-nudge recommendation, subsystem guess (or an honest "unclear").
- New skill `skills/issue-actions/`: the full decide-table — confirm bug/feature, mark
  duplicate, close out-of-scope, needs-more-info, assign, add-to-milestone, nudge author.
  Confirm-then-post throughout. Guardrail: `state`/`assignees`/`milestone` only ever on a real
  Issue number, verified via `issueOrPullRequest`/`issue_read` — never a PR.
- Relationship surfacing and staleness housekeeping (on request): blocking-issue text
  references, orphaned milestone issues, reverted-closer issues (best-effort), cross-PR/
  open-issue area overlap, milestone health; `needs-more-info` where the reporter already
  replied, long-stale issues, "fixed in vX" still-open issues.

### Phase 2 — PR decision-table completion, recommend-and-offer, write-scope expansion

All mechanical extensions of `pr-actions`/`pr-queue`, no new infra beyond the token-scope
change below.

- `distribution.yaml`: `GITHUB_TOKEN` description gains `Contents Write`.
- `config.yaml`: move `create_or_update_file`/`push_files` into
  `mcp_servers.github.tools.include`; regenerate the exclude-list comment's "exact complement"
  via the same live `tools/list` probe. `delete_file` and `merge_pull_request` stay excluded.
- `pr-actions/SKILL.md`: new **commit a fix** procedure (confirm exact content first, commit
  straight to the PR's own branch, report the SHA — never a merge, never another branch).
- **Request changes** becomes the compound action the table above specifies: post the review
  *and* apply `needs-author-action`, together, one confirmed action.
- **Defer**, **Flag conflict**, **Nudge the author**, **Apply e2e-gate-bypass** (explain +
  name the label, never apply it): new short procedures, each confirm-then-post.
- **Approve fork workflow run**: stays link-only — build the link from `actions_list`/
  `actions_get`'s own `html_url` (already granted).
- **Rebase cascade**: after a confirmed approval, re-check `sequence_prs`'s `rebase_flag` for
  downstream PRs, offer to comment, confirm, post.
- **Recommend-and-offer**: `pr-queue`'s queue presentation offers the guided walkthrough; its
  review brief's existing recommendation gets an offer to execute it in the same turn; the
  deep-dive's offer widens to the full relevant action menu (approve/request-changes/comment/
  label/ask in Discussion or Slack/act on the related issue).

### Phase 3 — Dashboard

New bundled plugin, `plugins/kyverno-dashboard/`:

- Tool half (same `__init__.py`/`tools.py` contract as `kyverno-fetch`/`kyverno-sequencer`):
  one tool, `update_dashboard(section, data)`, writing structured JSON to a local state file.
  Verify Hermes's real plugin writable-data-directory API live before picking a path.
- Dashboard-tab half: `dashboard/manifest.json` + `plugin_api.py` (FastAPI, reading that same
  state file, mounted at `/api/plugins/kyverno-dashboard/`) + `dist/index.js`/`style.css` — no
  build pipeline unless the manifest genuinely requires one.
- Real design effort — sortable/filterable, click-through to detail panels, not a JSON table
  dump. Every panel above (PR queue, issue, fork-approval, per-item detail, Discussions,
  session history) gets built here, each row carrying state + verdict + related items + link.
- Every confirmed write action from Phase 1/2 calls `update_dashboard` right after.

### Phase 4 — Session open/close, "what changed," proactive Discussions

Reads from all three other phases, so it lands last.

- New skill `skills/session/` (or folded into `pr-queue`'s Step 0 — decide the seam when
  implementing): session open recalls the last summary, runs the "what changed" diff (a small
  snapshot-vs-current comparison, reported as named transitions like `needs-author-action` →
  `ready-for-review`, not a bare count), surfaces relevant Discussions unprompted, then asks
  the focus question (now also offering issue triage and a specific PR/issue number).
- Session close: self-reports every confirmed action taken this conversation, `mnemosyne_
  remember`s it as the next session's "last summary," updates the dashboard's session history
  and milestone health, flags follow-ups.

### Verification

- Phase 1: an issue with two independent PRs shows both, flagged, with a progress synthesis;
  Slack/Discussions checked for issues the same as for PRs; `issue-actions` never touches
  `state`/`assignees`/`milestone` on a PR.
- Phase 2: `create_or_update_file` succeeds against a real PR branch with the new scope;
  Request Changes applies the review and the label together; the queue offers a walkthrough;
  a review brief offers to execute its own recommendation in the same turn.
- Phase 3: `hermes dashboard` shows the new tab; a Phase 1/2 action shows up with a timestamp
  within one session; re-running an action updates the entry rather than duplicating it.
- Phase 4: flip a real PR's label via Phase 2's tools, confirm the next session-open names
  that exact transition; confirm session close's summary matches the real actions taken.