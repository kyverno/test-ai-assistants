# Kyverno Maintainer Assistant — Reference

> Everything finalized in this conversation. Use this as the spec for all implementation work.

---

## The core problem

The session was fetching 15 of 107 PRs sequentially, taking 5 minutes, and the sequencer had no real data to work with. The bottleneck is the **data layer**, not the intelligence layer. No amount of skill rewriting fixes a capability gap in the fetch pipeline.

---

## What to build, in order

1. **Batched GraphQL fetch** — prerequisite for everything else
2. **AGENTS.md cache into mnemosyne** — fetch once on install, available every session
3. **Persistent HTML dashboard artifact** — created once, updated every session
4. **Proper sequencer** — full dependency graph (stacks, codegen edges, explicit body refs, closing issue conflicts, file/package overlap)
5. **gopls MCP integration** — semantic call graph edges on top of the working foundation (deferred, add after 1–4)

---

## Batched GraphQL fetch

A single aliased GraphQL query returns all ready-for-review PRs with file lists, labels, review states, milestone, and closing issues in **one network call**. The current sequential approach times out at ~15 PRs.

Also needs a `get_reviews` pass per candidate upfront (CodeRabbit approval + unresolved thread count) before calling the sequencer — currently fetched lazily inside the per-PR review step, too late to reach the sequencer.

---

## Sequencer — what it actually does

**The sequencer is a graph builder, not a decision maker.** It takes already-fetched PR metadata, builds a dependency graph, runs a topological sort, and returns structured tiers with annotations. The agent reads that output and makes the final recommendation — including ordering within free tiers, based on context the graph can't see.

The sequencer has no GitHub or Slack access. Pure computation, deterministic, no I/O.

### Why no CP-SAT or greedy solver

The soft weighted layer (CP-SAT / greedy) was solving the wrong problem. Ordering *within* free tiers — which of two unrelated PRs goes first — is a judgment call that belongs to the agent. The agent has Slack context, knows what the maintainer said last session, knows what they're trying to get done today. A weighted solver ignoring all of that produces an answer that looks precise but isn't trustworthy.

What the code is actually good at: graph math — what depends on what, what conflicts with what, what is structurally unsafe to reorder. The output should be tiers + annotations. The agent decides order within tiers.

### Dependency edge types

**Hard ordering constraints (DAG edges):**

| Edge | Detection | Rule |
|---|---|---|
| **Stacked** | `B.base_branch == A.head_branch` | A before B. B cannot merge until A merges. |
| **Generated file ordering** | A touches `api/**/*_types.go` or bumps `github.com/kyverno/api`; B touches `zz_generated.*`, `pkg/client/**`, etc. | A before B. Codegen must run after A merges. |
| **Explicit body reference** | B.body contains "Depends on #A", "Stacked on #A", "Blocked by #A" | A before B. Author declared the dependency. |
| **Closing issue conflict** | A and B both close the same issue | Flag for human — only one can actually close it. Neither gets ordered. |

Edges without a derivable direction are not guessed — go into `unresolved[]` with a reason.

**Annotations (not ordering edges):**

| Annotation | Meaning |
|---|---|
| `rebase_flag` | PR shares files with an earlier-positioned PR. Will need rebase after that one merges. |
| Package overlap | Different files, same package. Possible semantic conflict. "Review together." |
| Gate blocked | Target branch has an open e2e-failure issue and PR lacks bypass label. |

### Algorithm

1. **File classification** — each changed file: GENERATED > API_SURFACE > ADMISSION_CRITICAL > TEST_ONLY > STANDARD. Patterns ported from `skills/kyverno-context/SKILL.md`. Not re-derived at runtime.

   ```
   GENERATED:          zz_generated.*, pkg/client/**, config/crds/**,
                       charts/**/crds/**, cmd/cli/kubectl-kyverno/data/crds/**
   GENERATED INPUT:    api/**/*_types.go, github.com/kyverno/api bump in go.mod
   API_SURFACE:        api/kyverno/**, api/policyreport/**, api/reports/**
   ADMISSION_CRITICAL: pkg/engine/**, pkg/webhooks/**, pkg/cel/**
   TEST_ONLY:          *_test.go, test/**
   STANDARD:           everything else
   ```

2. **Build hard-edge DAG** — all edge types above. Unresolvable direction → `unresolved[]`. Package overlap → annotation only, no edge.

3. **Cycle detection** — Kahn's algorithm. Cycles never silently broken. Cycle members → `cycles[]`, excluded from sequence entirely.

4. **Topological sort** → produces ordered tiers. Within each tier, PRs have no hard ordering constraint between them. The sequencer does not order within tiers — it returns them flat, and the agent decides.

5. **Annotate** — per PR: `rebase_flag`, package overlap warnings, gate blocked status. All surfaced explicitly so the agent can name them.

### Output JSON

```json
{
  "tiers": [
    {
      "tier": 1,
      "prs": [
        {
          "pr": 17698,
          "hard_constraints": ["must precede #17701 (stacked)"],
          "rebase_flag": false,
          "warnings": [],
          "gate_blocked": false,
          "file_classification": "API_SURFACE"
        }
      ]
    },
    {
      "tier": 2,
      "prs": [
        {"pr": 17701, "hard_constraints": ["must follow #17698 (stacked)"], ...},
        {"pr": 17705, "hard_constraints": [], "warnings": ["package overlap with #17701 (pkg/engine)"], ...}
      ]
    }
  ],
  "cycles": [[17710, 17711]],
  "unresolved": [{"prs": [17720, 17721], "why": "both close #1234"}],
  "gate_status": {"open": true, "issue": 1567},
  "package_overlaps": [{"prs": [17701, 17705], "package": "pkg/engine"}]
}
```

Within tier 2 above, `#17701` and `#17705` have no hard ordering constraint between them. The agent decides which goes first, using context the graph doesn't have.

### What labels do NOT exist

`release-critical`, `release-high`, `release-medium`, `release-low` — **these labels are gone from kyverno**. Remove every reference to them from all files.

---

## Agent role — facts vs verdict

**Sequencer owns:** file classification, hard dependency edges, cycle detection, topological sort, risk/warning annotations, tiers.

**Agent owns:** ordering within free tiers (using Slack context, maintainer preferences, session history), stating the final recommendation, explicitly saying when and why it agrees or disagrees, cross-referencing anything the graph can't see.

**The verdict framing rule:** The tiers and annotations are a structural report, not a merge order. The agent presents its recommendation, citing the structure where it's determinative and its own reasoning where it isn't.

**Step 0 rule:** If the maintainer hasn't specified a focus, ask before fetching. Options: milestone, author, area (package/directory), `workflow-approval-required`. Do not default to oldest-first or all-PRs.

**Every PR in the same format.** Human or Dependabot — same template, same queue. No special Dependabot section.

**`workflow-approval-required` PRs:** Named separately at the end. Not in the review sequence. Not in sequencer input.

---

## Milestone field

PRs now carry a **direct milestone field**. Do not infer milestone from closing issues. Query directly:

```bash
gh search prs --repo kyverno/kyverno --label ready-for-review \
  --milestone "Kyverno Release X.Y.Z" --state open
```

Or in GraphQL: `pullRequest { milestone { title } }`.

---

## Label taxonomy

| Label | Meaning |
|---|---|
| `ready-for-review` | Closes a milestone issue AND no failing CI AND no merge conflicts. |
| `needs-author-action` | Failing CI or review requested changes the author must fix. |
| `needs-review` | Waiting for reviewer. |
| `milestone-pr` | Stamped by pr-readiness-check during sweep for PRs closing milestone issues. |
| `merge-conflicts` | Auto-applied by workflow. |
| `e2e-gate-bypass` | Human-only. Never auto-applied. Annotated in sequencer output, listed separately in agent output. |
| `e2e-failure` | On the e2e-failure tracking issue (not PRs). Signals gate is open for that branch. |
| `workflow-approval-required` | Fork PRs needing approval before CI. Listed separately in agent output. |

---

## Dashboard artifact

The dashboard is a persistent HTML artifact on claude.ai. One URL for the lifetime of the profile installation. The agent fills it, edits it, and updates it during and between sessions. The maintainer has everything in front of them with proper links.

### Creation and persistence

- Created once on first install. URL stored in mnemosyne under `kyverno-dashboard-url`.
- Every session: agent reads URL from mnemosyne, updates the artifact in place. Never creates a duplicate.
- Pre-built template ships with the profile. `scripts/install.sh` publishes it on first install and stores the URL.

### What the dashboard contains

**Session header**
- Current date, milestone in focus, where things were left last session (pulled from mnemosyne session summary)
- Quick status: number of ready PRs, gate status, PRs needing maintainer action

**PR Queue panel**
- PRs in tier order from the sequencer
- Per PR: number + title (linked to GitHub PR), tier, hard constraints if any, warnings, review state, milestone linkage
- Within-tier ordering reflects the agent's judgment from that session
- PRs the maintainer approved or acted on are marked done with timestamp

**`workflow-approval-required` PRs**
- Separate section, not in the queue
- Each one linked to its GitHub PR and workflow run

**Individual PR panels** (added as maintainer dives in)
- Full review brief for that PR: file classification, changed files, linked issue, CI status, CodeRabbit summary, unresolved threads with links
- Discussion context: key comments from the PR and any linked GitHub Discussion, with links
- What the agent recommended and why
- What the maintainer decided

**GitHub Discussions panel**
- Active discussions relevant to the current milestone or focus area
- Linked to the discussion on GitHub
- Agent summarizes context; maintainer can ask the agent to go deeper on any discussion

**Session history**
- What was reviewed last session, what was merged, what was deferred, what is waiting on author
- Links to all PRs touched

**Future:** actions panel (approve, request changes, queue for merge) — not in scope now, noted for later.

---

## Plugin packaging — verified against Hermes source

- `plugins/kyverno-sequencer/` ships automatically — `distribution.yaml` has no `distribution_owned:` key.
- Discovered at `~/.hermes/profiles/kyverno/plugins/kyverno-sequencer/` — no env var, no opt-in.
- Requires `plugin.yaml` + `__init__.py` exposing `register(ctx)`.
- Must be listed in `config.yaml plugins.enabled:`.
- Tool must be in a granted toolset in `config.yaml custom_toolsets:`.
- OR-Tools is not needed anymore (no CP-SAT layer). Sequencer is pure stdlib — no external dependencies.

---

## Security invariants

- **No merge tool.** Agent cannot merge PRs. Enforced at Hermes allowlist, token scope, hook backstop.
- **Token: read + limited write.** No merge, no admin, no Contents-write.
- **`e2e-gate-bypass` never auto-applied.** Agent suggests it. Maintainer applies it.
- **No laptop-level tools.** `config.yaml` disables terminal, file, browser, code_execution, computer_use, connections, delegation.
- **Plugin trust is explicit.** Must be in `custom_toolsets:` AND granted toolsets list.