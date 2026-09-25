# kyverno-assistant

An on-demand PR review queue assistant for a Kyverno maintainer, built as a
[Hermes profile distribution](https://hermes-agent.nousresearch.com/docs/user-guide/profile-distributions):
`distribution.yaml` + `SOUL.md` + `config.yaml` (which declares the GitHub and
Slack MCP servers directly — no separate `mcp.json`) + `skills/` + `hooks/`.
One maintainer installs it, fills in their own credentials, and talks to it on
Slack or via `kyverno chat` — no server to run, no webhook receiver.

**Status: skills written, not yet installed anywhere.** `distribution.yaml` /
`SOUL.md` / `config.yaml` / `hooks/` and all three skills (`kyverno-context`,
`pr-queue`, `pr-actions`) exist and are internally consistent — every tool
each skill references is actually granted in `config.yaml`, and vice versa
(cross-checked, not assumed). What's still missing: a real `hermes profile
install` has never been run against this repo, so none of it has executed
inside an actual Hermes process, and the validation-with-2-3-maintainers step
(`docs/deployment.md`) hasn't started. Before graduating to a dedicated
`kyverno/kyverno-assistant` repo, both of those still need to happen.

## Quick start

```bash
hermes profile install . --name kyverno --alias -y   # local checkout, while prototyping
kyverno chat
```

See `docs/deployment.md` for the full env var list and Slack app setup.

## What it does (v1, written but not yet run for real)

Fetches PRs where the maintainer is a requested reviewer (`pr-queue`),
filters to ready-for-review using this repo's actual live label set — never
a hardcoded name (`kyverno-context`) — and produces a ranked queue that
explains itself: stacked-PR ordering, generated-file conflicts between
queued PRs, and per-PR post-merge CI risk (`docs/architecture.md` covers why
that last one matters specifically on this codebase). Explains any PR on
request, synthesizing Copilot/CodeRabbit review output, and can also answer
open-ended questions about the repo or queue by looking things up rather
than guessing (`docs/architecture.md`, "Maintainer questions are
open-ended"). Labels, comments, requests changes, approves, and catches a
PR's branch up with its base (`pr-actions`) using the maintainer's own
credentials — note that's a GitHub-API merge-update, not a git rebase, even
when a maintainer asks to "rebase"; see that skill for why.

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
- `skills/kyverno-context/` — dynamically-resolved labels/CODEOWNERS
  (never hardcoded — re-resolved live every session) plus Kyverno's real
  codegen fan-out and pre-/post-merge CI split, and on-demand doc lookup
  via `search_code`.
- `skills/pr-queue/` — fetch, filter, rank, and explain the review queue;
  tools + fixed facts + "look, don't guess," not a fixed script per
  question (see `docs/architecture.md`).
- `skills/pr-actions/` — label/comment/request-changes/approve/branch-update,
  all via the maintainer's own token; explicit about what it can't do
  (merge, true rebase, post-merge CI monitoring) and why.
- `docs/architecture.md` / `docs/deployment.md` — design and install runbook.
- `docs/archive/` — operational notes from the abandoned `kyctrl` design
  this repo previously held (kept for reference, not part of this project).
