# kyverno-assistant

An on-demand PR review queue assistant for a Kyverno maintainer, built as a
[Hermes profile distribution](https://hermes-agent.nousresearch.com/docs/user-guide/profile-distributions):
`distribution.yaml` + `SOUL.md` + `config.yaml` (which declares the GitHub and
Slack MCP servers directly — no separate `mcp.json`) + `skills/` + `hooks/`.
One maintainer installs it, fills in their own credentials, and talks to it on
Slack or via `kyverno chat` — no server to run, no webhook receiver.

**Status: skeleton only.** `distribution.yaml` / `SOUL.md` / `config.yaml` are
written and their toolset allowlist is verified against the real upstream
servers (see `docs/architecture.md`). The `skills/` referenced below —
`kyverno-context`, `pr-queue`, `pr-actions` — don't exist yet; nothing in
"What it does" is functional yet. Before graduating to a dedicated
`kyverno/kyverno-assistant` repo, those skills still need writing and a real
`hermes profile install` needs to be run against them.

## Quick start

```bash
hermes profile install . --alias kyverno   # local checkout, while prototyping
kyverno chat
```

See `docs/deployment.md` for the full env var list and Slack app setup.

## What it's meant to do (v1, not built yet)

Fetch PRs where the maintainer is a requested reviewer, filter to
ready-for-review, and produce a ranked queue that explains itself —
including stacked-PR ordering, generated-file conflicts between queued PRs,
and per-PR post-merge CI risk (see `docs/architecture.md` for why that last
one matters on this codebase specifically). Explain any PR on request,
synthesizing Copilot/CodeRabbit review output. Label, comment,
request-changes, approve, and rebase using the maintainer's own credentials.
This is the design `skills/` will implement — see the status note above.

**Cannot merge** — no merge tool exists in its toolset, enforced in three
independent, verified layers. See `docs/architecture.md`.

## Layout

- `distribution.yaml` — install manifest: name, version, required env vars.
- `SOUL.md` — the agent's identity and boundaries.
- `config.yaml` — model default, the GitHub/Slack MCP server declarations
  (`mcp_servers:`), and the hand-picked tool allowlist. Security-critical,
  hand-edited only.
- `hooks/block-dangerous-tools.sh` — a `pre_tool_call` backstop that rejects
  any merge/delete-repo/force-push-shaped tool call.
- `skills/kyverno-context/` *(not yet written)* — dynamically-resolved
  labels/CODEOWNERS plus Kyverno's real codegen fan-out and pre-/post-merge
  CI split.
- `skills/pr-queue/` *(not yet written)* — fetch, filter, rank, and explain
  the review queue.
- `skills/pr-actions/` *(not yet written)* — label/comment/request-changes/
  approve/rebase.
- `docs/architecture.md` / `docs/deployment.md` — design and install runbook.
- `docs/archive/` — operational notes from the abandoned `kyctrl` design
  this repo previously held (kept for reference, not part of this project).
