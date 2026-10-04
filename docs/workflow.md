# Kyverno Maintainer Workflow — What the Agent Does

---

## The model

The agent eliminates mechanical work. The maintainer **decides**; the agent prepares, drafts, and executes. Every action on GitHub requires explicit maintainer confirmation — no silent writes, ever.

---

## Session open

1. Agent reads what happened last session — what was reviewed, what merged, what's waiting on authors, what was deferred, what issues were triaged.
2. Agent fetches what changed since then: new PRs, PRs that got CI fixes or new reviews, new issues opened, gate status on any branch.
3. Agent asks: **what's the focus today?**
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

No maintainer action yet. Just orient.

### 2. Per PR — brief
Maintainer picks a PR, or agent recommends where to start. Agent presents:
- What the PR does, what files it touches, which subsystem
- Linked issue it closes
- CI status, CodeRabbit summary, unresolved review threads with direct links
- Key comments from the PR and any linked GitHub Discussion
- Agent's recommendation: approve / request changes / defer, and why

### 3. Per PR — maintainer decides

| Decision | What happens |
|---|---|
| **Approve** | Agent posts approval via GitHub API. Marks done in dashboard with timestamp. |
| **Request changes** | Agent drafts the review comment incorporating maintainer's notes. Maintainer confirms or edits the draft. Agent posts it. Applies `needs-author-action` label. |
| **Defer** | Agent records reason in memory. Marks deferred in dashboard. No GitHub action. |
| **Flag conflict** | Agent drafts a comment on the PR flagging the conflict (e.g. two PRs closing the same issue). Maintainer confirms. Agent posts it. |
| **Apply e2e-gate-bypass** | Agent cannot do this. Agent explains why it's needed and what label to apply. Maintainer applies it manually. |
| **Approve fork workflow run** | Agent cannot do this. Agent links to the GitHub Actions approval page. Maintainer approves in browser. |

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
- If a PR already exists that might address it: links to it
- Which subsystem it likely affects

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

### 3. Issue relationship surfacing
On request, agent surfaces the issue graph:
- Issues blocking other issues (detected from issue body text)
- Orphaned milestone issues — in the milestone, no PR, no assignee
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

1. Agent summarizes what happened: approvals posted, review comments sent, issues triaged, labels applied, deferred items with reasons.
2. Writes session summary to memory — available at the start of next session.
3. Updates dashboard: marks completed items with timestamp, updates deferred list, updates milestone health.
4. Flags follow-ups: PRs waiting on author response, issues waiting on more-info reply, PRs at risk of merge conflict.

---

## What the agent cannot do

- Merge PRs — hard block at token scope, never negotiable
- Apply `e2e-gate-bypass` — agent suggests, maintainer applies manually
- Approve workflow runs — agent links to the page, maintainer approves in browser
- Any GitHub write without the maintainer confirming the drafted action first

---

## Dashboard

The dashboard is a persistent page, one URL for the lifetime of the installation. The agent updates it during and between sessions. The maintainer has everything in one place with proper links.

**Session header**
Current date, milestone in focus, where things were left last session, quick status: ready PRs, gate status, PRs needing maintainer action, open issues vs milestone total.

**PR queue panel**
PRs in tier order. Per PR: number + title linked to GitHub, tier, hard constraints if any, warnings, review state, milestone linkage. PRs the maintainer acted on are marked with timestamp and what action was taken.

**Fork PRs needing workflow approval**
Separate section. Each linked to its GitHub PR and the Actions run awaiting approval.

**Per-PR detail panels** (added as maintainer dives in)
Full brief: file classification, changed files, linked issue, CI status, CodeRabbit summary, unresolved threads with links, key comments, any linked Discussion. What the agent recommended. What the maintainer decided.

**Issue panel**
Milestone health — open issues, issues with active PRs, orphaned issues. Triage queue — new issues since last session. Relationship flags — duplicate candidates, blocked issue chains, reverted-closer issues, staleness flags.

**GitHub Discussions panel**
Active discussions relevant to the current milestone. Linked to GitHub. Agent-summarized with status and what decision (if any) is pending.

**Session history**
What was reviewed, approved, deferred, triaged, closed last session. Links to everything touched.