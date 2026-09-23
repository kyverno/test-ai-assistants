---
name: kyverno-context
description: "Live labels/CODEOWNERS lookup; Kyverno's codegen & CI facts."
version: 0.1.0
author: Suhaani Agarwal, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
---

# kyverno-context Skill

Resolves two different kinds of knowledge `pr-queue` and `pr-actions` both
depend on: `KYVERNO_REPO`'s actual label taxonomy and CODEOWNERS (looked up
live, every session — never assumed), and Kyverno's real codegen fan-out and
CI structure (fixed facts about the build system, documented here rather than
re-derived every time). Does not read PR content itself — that's `pr-queue`.

## When to Use

- Before filtering PRs by any label-based state (e.g. "is this ready for
  review") — there is no fixed label vocabulary to assume.
- Before labeling a PR (`pr-actions`) — to use a label that actually exists.
- When deciding whether `MAINTAINER_GITHUB_LOGIN` is a requested reviewer for
  a given changed path via CODEOWNERS, including team-based ownership.
- Don't use for: reading a PR's own diff, reviews, or comments — `pr-queue`
  calls those tools directly.

## Prerequisites

- `GITHUB_TOKEN` and `KYVERNO_REPO` (`owner/repo`) from the profile's `.env`.
- `mcp-github` tools: `list_label`, `get_file_contents`, `get_team_members`,
  `get_teams`, `search_code`.

## Quick Reference

- `list_label(owner, repo)` — every label `KYVERNO_REPO` actually has.
- `get_file_contents(owner, repo, path="CODEOWNERS")` — raw CODEOWNERS text.
- `get_team_members(org, team_slug)` — resolve a `@org/team` CODEOWNERS entry
  against `MAINTAINER_GITHUB_LOGIN`.
- `search_code(query="<terms> repo:${KYVERNO_REPO}")` — find a repo doc
  (`AGENTS.md`, `CONTRIBUTING.md`, `docs/**`) or a symbol's other usages on
  demand, scoped to what the current question needs. Always include
  `repo:${KYVERNO_REPO}` — unqualified, this searches all of GitHub, not
  just this repo.

## Procedure

1. At the start of each session, call `list_label` against `KYVERNO_REPO` and
   hold the result for the rest of the session. Never assume a label like
   "ready-for-review" exists without having seen it in this call —
   `kyverno/kyverno`'s real label set has no such label as of this writing
   (confirmed by listing it directly; see Pitfalls for why this is checked
   per-session, not assumed from a prior run).
2. Call `get_file_contents` for `CODEOWNERS` at the repo root. Parse it as an
   ordered list of `(path-pattern, owner)` pairs, top to bottom. An owner is
   either an individual (`@user`) or a team (`@org/team-slug`).
3. To find who owns a given changed path: walk the CODEOWNERS lines in file
   order and keep the *last* line whose pattern matches — GitHub's own rule
   is last-match-wins, not longest-pattern-wins (a later, broader pattern
   overrides an earlier, narrower one if it comes after it in the file). If
   that owner is a team, call `get_team_members` to check whether
   `MAINTAINER_GITHUB_LOGIN` is a member before concluding they're a
   requested reviewer for that path.
4. Re-resolve both label list and CODEOWNERS at the start of every new
   session — don't reuse a value from a previous session's memory. This
   instance may be repointed at a different `KYVERNO_REPO` between sessions
   (sandbox → `kyverno/kyverno`), and a stale answer from one repo is
   actively wrong for the other.

## Reference: Kyverno's codegen fan-out (fixed fact, not repo metadata)

Verified directly against `kyverno/kyverno`'s `Makefile` — anything under
`api/**` fans out to:

- `codegen-api-register` → `zz_generated.register.go`
- `codegen-api-deepcopy` → `zz_generated.deepcopy.go`
- clientset/lister/informer regeneration
- CRD regeneration (`config/crds`), Helm chart regen, `docs/user/crd` regen

`check-codegen.yaml` gates this pre-merge on `kyverno/kyverno` itself. The
practical consequence for `pr-queue`: two open PRs that both touch `api/**`
will conflict on these *generated* files even when their own diffs don't
overlap — flag this as a generated-file conflict, not just a normal merge
conflict.

## Reference: Kyverno's pre-merge vs post-merge CI split (fixed fact)

Verified directly against `kyverno/kyverno`'s `.github/workflows/`:

- **Pre-merge** (`pull_request`-triggered, gates the PR): `check-codegen.yaml`,
  `check-unit-tests.yaml`, `check-golangci-lint.yaml`, `check-vet.yaml`,
  `check-imports.yaml`, `check-fmt.yaml`, `check-cli-tests.yaml`,
  `check-framework.yaml`, `check-ct-lint.yaml`, `check-ah-lint.yaml`,
  `check-devcontainer.yaml`, `check-unused-package.yaml`,
  `check-sha-pinned-actions.yaml`.
- **Post-merge only** (`push`-to-`main`-triggered via `check-tests.yaml`,
  never runs on a PR): `tests-conformance.yaml` (Chainsaw-style, matrixed
  across 3 k8s versions), `tests-conformance-policy-library.yaml` (12-way
  sharded), `tests-k6.yaml`, performance benchmarks.

Nothing catches a bad interaction between two individually-green PRs before
both land on `main`. This is why `pr-queue` reasons about which packages a PR
touches that map to the post-merge-only suites as a real risk signal, not
just whether its own pre-merge checks are green.

## Pitfalls

- Don't carry a label list or CODEOWNERS parse across sessions or across a
  `KYVERNO_REPO` change — always re-resolve (step 4 above).
- Last-match-wins for CODEOWNERS, not longest-pattern or first-match — a
  broad `*` line after a narrow one *does* override it if it comes later in
  the file.
- The codegen/CI-split facts above are frozen at this research pass
  (2026-09-22 research vs `kyverno/kyverno`'s `main`). If a merge-order
  decision materially depends on them and it's been a while, re-verify with
  `get_file_contents` on `Makefile` / `.github/workflows/check-tests.yaml`
  rather than trusting this file blindly.
- There's no dedicated milestone-listing tool in `github-mcp-server` —
  milestone data comes from fields on `list_pull_requests`/
  `search_pull_requests` results, which `pr-queue` reads directly; this
  skill doesn't handle milestones.
- Don't preload every repo doc every session — `search_code` on demand,
  scoped to the current question, not eagerly.

## Verification

- Ask "what labels does `<repo>` have" for two different `KYVERNO_REPO`
  values in one session and confirm `list_label` is actually called each
  time, not answered from a repeated/memorized list.
- Ask "does `<path>` need sign-off from `<team>`" and confirm the answer
  comes from a real `get_file_contents` + `get_team_members` call, not a
  guess.
