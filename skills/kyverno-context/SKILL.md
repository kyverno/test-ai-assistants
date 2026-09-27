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

The API types are split across **two repos**, verified against
`api/AGENTS.md` and `docs/context/shared/{repo-boundaries,api-versioning}.md`
on `kyverno/kyverno`'s `main`: `kyverno.io` (`v1`/`v1beta1`/`v2`/`v2alpha1`/
`v2beta1`), `wgpolicyk8s.io` (as `policyreport`), and `reports.kyverno.io`
live in this repo's own `api/**`. The CEL-based `policies.kyverno.io` types
(`ValidatingPolicy`, `MutatingPolicy`, `GeneratingPolicy`, `DeletingPolicy`,
`ImageValidatingPolicy`, `PolicyException`, and their `Namespaced*` variants)
live in the **separate `github.com/kyverno/api` Go module**, pinned in
`go.mod` — a PR in `kyverno/kyverno` can never touch those type definitions
directly; the equivalent generated-input event for that half of the surface
is a `go.mod`/`go.sum` bump of `github.com/kyverno/api` (shaped like a
Dependabot dependency bump, not an `api/**` diff).

Every generated no-edit path, verified directly against `kyverno/kyverno`'s
own `.claude/settings.json` (`permissions.deny`) — the maintainers' own
machine-enforced list, more precise than inferring from the `Makefile`
alone:

- `zz_generated.deepcopy.go`, `zz_generated.register.go` — from
  `codegen-api-register`/`codegen-api-deepcopy`, `api/**/*_types.go` input.
- `/pkg/client/**` — the whole generated clientset/listers/informers tree,
  for *both* API groups above (client-gen's inputs include the external
  module's `policies.kyverno.io` types alongside this repo's own).
- `/pkg/clients/**/*.generated.go`, `/pkg/clients/**/interface.generated.go`
  — the instrumented client-wrapper layer (`make codegen-client-wrappers`).
  Notably carries **no** `// DO NOT EDIT` header, unlike every other
  generated zone here — path-matching is the only reliable signal for this
  one, not the header. `pkg/clients/dclient`'s hand-written `client.go` is
  the one real exception in this directory: genuinely hand-maintained, not
  generated, despite living alongside generated siblings.
- `/config/crds/**/*.yaml`, `/cmd/cli/kubectl-kyverno/config/crds/**` — CRD
  manifests (`codegen-crds-*`), one target per API group plus a CLI-specific
  one.
- `/cmd/cli/kubectl-kyverno/data/crds/**` — a **second-order copy** of
  specific `config/crds/**` files into the CLI's embedded data, via
  `codegen-cli-crds`. A PR that updates `config/crds/**` by hand without the
  matching `data/crds/**` copy is itself generated-file-conflict-shaped —
  flag it even with no second PR involved.
- `/charts/kyverno/charts/crds/templates/*/**`, `/charts/**/README.md` — a
  **third** CRD-content target (the Helm chart's embedded CRDs) plus
  helm-docs-generated READMEs, via `codegen-helm-all`.
- `/docs/user/crd/**` — API reference docs, via `codegen-api-docs`.
- `/pkg/config/mocks/mock_config.go`, `/config/install-latest-testing.yaml`
  — narrower generated single files, not fed by `api/**` but still no-edit.

Outside `pkg/clients` (the documented exception above), the reliable signal
for "this specific file is generated" is the `// Code generated ... DO NOT
EDIT.` header — the filename pattern (`zz_generated.*`) is one instance of
that convention, not the whole rule, per `api/AGENTS.md` directly.

`check-codegen.yaml` gates all of this pre-merge on `kyverno/kyverno`
itself. The practical consequence for `pr-queue`: two open PRs whose diffs
both feed the same generated-output path above will conflict on that
*generated* file even when their own diffs don't overlap — including a
`kyverno/kyverno` PR touching `api/**` alongside a Dependabot PR bumping
`github.com/kyverno/api`, since both feed clientset/CRD regeneration. Flag
this as a generated-file conflict, not just a normal merge conflict.

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
  across 3 k8s versions, fixtures under `test/conformance/chainsaw/**` and
  `test/chainsaw/**` in this repo), `tests-conformance-policy-library.yaml`
  (12-way sharded), `tests-k6.yaml`, performance benchmarks.

`tests-conformance-policy-library.yaml` checks out the **separate
`kyverno/policies` repo** and runs that freshly-built binary against its
policy corpus — the suite isn't scoped to any package in `kyverno/kyverno`
at all; it exercises whatever surface a real-world policy sample reaches
(engine, CEL evaluation, image verification, webhooks routing, ...) end to
end. This is the real reason `kyverno-context` doesn't attempt a
path-to-suite mapping (see Pitfalls/test-scenarios' honesty-test scenario):
one of the two biggest post-merge suites genuinely isn't package-scoped, so
a precise mapping for it would be fabricated, not derived. `pr-queue` treats
a PR touching core policy-evaluation surface (`pkg/engine`, `pkg/cel`,
`pkg/validation`, `pkg/image`, `pkg/webhooks`) as elevated post-merge risk
on that basis, not from a specific package→suite table.

Nothing catches a bad interaction between two individually-green PRs before
both land on `main` — true for the *first* such interaction. See the
`e2e-gate` reference below for what happens after that first failure lands.

## Reference: `e2e-gate` — reactive post-merge block (live on `main` today)

Verified directly against `.github/workflows/e2e-gate.yaml` on
`kyverno/kyverno`'s real `main` branch. When the post-merge-only conformance suite (`tests-*.yaml` via
`check-tests.yaml`) fails on a branch, an `e2e-failure`-labelled tracking
issue opens and a required "E2E Gate" commit status turns red on every open
PR targeting that branch, blocking further merges until either the issue is
closed or the specific fixing PR carries `e2e-gate-bypass`. Refines, doesn't
replace, the fact above: the *first* bad interaction between two green PRs
still lands undetected, but a post-merge failure it causes does reactively
block everything else behind it, not silently let more PRs stack on a broken
`main`. When `pr-queue` flags post-merge risk, check whether an
`e2e-failure` issue is already open for the target branch — if so, the
whole queue is currently gated, not just the flagged PR.

## Reference: file-risk classification vocabulary (for merge-sequencing)

Three tiers `pr-queue` uses to classify a PR's changed files when building a
merge-sequence recommendation, most to least constraining:

- **Generated** — a file matching the codegen fan-out map above: any of the
  `.claude/settings.json`-sourced paths, a `// Code generated ... DO NOT
  EDIT.` header, or (`pkg/clients` only) the `*.generated.go`/
  `interface.generated.go` filename convention with no header. On the
  *input* side: `api/**/*_types.go` in this repo, or a `go.mod`/`go.sum`
  bump of `github.com/kyverno/api` (the external-module equivalent). Two
  candidates both touching generated-file *inputs* that feed the same
  output conflict on that output even with zero diff overlap — order
  input-before-output when one candidate is literally the codegen/bump
  run itself, otherwise flag the pair for a human rather than guessing an
  order. Check this tier *first*: a file can look interface-like
  (`pkg/clients/**/interface.generated.go`) while actually being generated
  output — Generated takes precedence over Interface when a path matches
  both.
- **Interface** — a hand-written file defining a Go interface, exported
  type, or public function signature that other in-flight candidates' diffs
  call or implement — concrete real examples in this codebase:
  `pkg/clients/dclient`'s `Interface` (`client.go`, hand-maintained, the one
  non-generated file in its directory), `pkg/client/clientset/versioned`'s
  top-level `Interface`, `pkg/engine/api`'s engine/context-loader
  interfaces. Approximated via `search_code`, not a real call graph — see
  `docs/architecture.md`. Order definer-before-implementer when the
  direction is unambiguous from the diffs; flag as a cycle for a human
  otherwise.
- **Test-only** — a `*_test.go` file anywhere, or any path under `test/**`
  (`test/conformance/chainsaw/**`, `test/chainsaw/**`, `test/cli/**`,
  `test/policy/**`, `test/fuzz/**`, and the rest of `test/`'s
  subdirectories — none of them require production-code changes to
  exercise), with no production-code change alongside. Lowest constraint:
  sequence by milestone-alignment/age, not file overlap.

A file can be unclassified (touches none of the above) — that's the common
case, not an error; it just means file-overlap conflict detection (plain
path intersection) is the only signal for that file, no risk tier attached.

## Reference: readiness-label taxonomy (from `.github/labels.yml`)

- `ready-for-review` — clean: DCO/CI/conflicts (+ review threads for human
  PRs) all pass. Applied by `pr-readiness-check.yaml` (human PRs) or
  `dependabot-merge-triage.yaml` (Dependabot PRs).
- `needs-author-action` — a real finding on a human PR (failing DCO/CI, the
  `merge-conflicts` label present, or an unresolved review thread whose last
  comment isn't the author's). Paired with a one-time itemized comment
  naming which.
- `needs-review` — the Dependabot equivalent: not confirmed patch/minor, or
  not clean, or Copilot didn't recommend approval.
- `major-bump` — informational, permanent, always paired with
  `needs-review`: a major-semver Dependabot bump, or one whose semver level
  couldn't be confirmed from the commit trailers at all.
- `ai-generated` / `spam` — CodeRabbit slop-detection and spam-burst flags,
  not part of the merge-sequencing logic itself.

This is real ground truth for what the taxonomy looks like, kept here as
context — it does **not** change step 1's live-resolution rule below.
`list_label` is still called every session; don't assume a name from this
list is present without having seen it in that call.

## Pitfalls

- Don't carry a label list or CODEOWNERS parse across sessions or across a
  `KYVERNO_REPO` change — always re-resolve (step 4 above).
- Last-match-wins for CODEOWNERS, not longest-pattern or first-match — a
  broad `*` line after a narrow one *does* override it if it comes later in
  the file.
- The codegen/CI-split, `e2e-gate`, and label-taxonomy facts above are
  frozen at the research pass that produced them. If a merge-order decision
  materially depends on any of them and it's been a while, re-verify with
  `get_file_contents` on `Makefile` / `.github/workflows/` /
  `.claude/settings.json` (`permissions.deny`, the generated-path source) /
  `api/AGENTS.md` / `docs/context/shared/{repo-boundaries,api-versioning}.md`
  rather than trusting this file blindly — the two-repo API split in
  particular is a real architectural fact, not just a path list, and worth
  re-checking if `kyverno/api` is ever folded back into this repo (the
  `repo-boundaries.md` doc explicitly flags that as a live possibility, not
  a settled decision).
- There's no dedicated milestone-listing tool in `github-mcp-server` —
  milestone data comes from fields on `search_pull_requests` results and
  its `milestone:"name"` query qualifier. That qualifier is
  `search_pull_requests`-only: `search_issues` takes a natural-language
  query, not GitHub qualifier syntax, and has no equivalent (see
  `pr-queue`'s Pitfalls). This skill doesn't handle milestones either way.
- Don't preload every repo doc every session — `search_code` on demand,
  scoped to the current question, not eagerly.

## Verification

- Ask "what labels does `<repo>` have" for two different `KYVERNO_REPO`
  values in one session and confirm `list_label` is actually called each
  time, not answered from a repeated/memorized list.
- Ask "does `<path>` need sign-off from `<team>`" and confirm the answer
  comes from a real `get_file_contents` + `get_team_members` call, not a
  guess.
