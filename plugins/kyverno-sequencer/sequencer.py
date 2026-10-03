"""Deterministic PR merge-sequencing core.

Pure computation over already-fetched PR metadata — no GitHub/Slack calls, no state. Two kinds
of ordering signal, kept structurally separate:

1. Hard precedence edges: some computed here mechanically from changed-file classification
   (stacked branches, generated-file input-before-output), some supplied by the caller as
   `precedence_hints` (interface definer-before-implementer, dependency-usage) because those
   genuinely require reading diffs / call-site search that this module has no access to — see
   skills/pr-queue/SKILL.md's Procedure. Either way, once an edge exists it's treated the same:
   fed into cycle detection and the solver as a hard constraint.
2. Soft priorities (milestone urgency, age, size, e2e-gate risk, review-readiness): blended into
   one weighted objective and solved for optimally with CP-SAT (falls back to a greedy
   weighted-priority heuristic if `ortools` isn't installed) rather than a lexicographic
   tie-break, since these factors genuinely trade off against each other.

File-risk classification patterns below are a code mirror of
skills/kyverno-context/SKILL.md's "Reference: file-risk classification vocabulary" and codegen
fan-out sections. Keep both in sync manually if Kyverno's generated-path list changes.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# --- file-risk classification (mirror of kyverno-context SKILL.md) --------------------------

GENERATED_GLOB_PATTERNS = [
    "zz_generated.deepcopy.go",
    "zz_generated.register.go",
    "pkg/client/*",
    "pkg/clients/*.generated.go",
    "pkg/clients/*/interface.generated.go",
    "config/crds/*.yaml",
    "cmd/cli/kubectl-kyverno/config/crds/*",
    "cmd/cli/kubectl-kyverno/data/crds/*",
    "charts/kyverno/charts/crds/templates/*",
    "charts/*/README.md",
    "docs/user/crd/*",
    "pkg/config/mocks/mock_config.go",
    "config/install-latest-testing.yaml",
]

# The one documented hand-written exception inside an otherwise-generated directory
# (kyverno-context: "pkg/clients/dclient's hand-written client.go is the one real exception").
GENERATED_EXCEPTIONS = {"pkg/clients/dclient/client.go"}

# Generated-file *inputs*, in this repo. The external-module equivalent (a go.mod/go.sum bump
# of github.com/kyverno/api) is checked separately via `dependency_bumps`, not a file path.
GENERATED_INPUT_GLOB_PATTERNS = ["api/*_types.go"]
GENERATED_INPUT_DEPENDENCY_MODULE = "github.com/kyverno/api"

TEST_ONLY_GLOB_PATTERNS = ["*_test.go", "test/*"]


def _norm(pattern: str) -> str:
    """fnmatch's '*' already matches path separators, so a doc-style '**' collapses to '*'."""
    return pattern.replace("**", "*")


def _match_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, _norm(pat)) for pat in patterns)


def classify_file(path: str) -> str:
    """'generated' | 'generated_input' | 'test' | 'unclassified'.

    Generated is checked first — a path can look like anything else while actually being
    generated output (kyverno-context: "Generated takes precedence ... when a path matches
    both"). Interface classification isn't attempted here: direction between an interface's
    definer and implementer needs diff content, not a path list — see `precedence_hints`.
    """
    if path not in GENERATED_EXCEPTIONS and _match_any(path, GENERATED_GLOB_PATTERNS):
        return "generated"
    if _match_any(path, GENERATED_INPUT_GLOB_PATTERNS):
        return "generated_input"
    if _match_any(path, TEST_ONLY_GLOB_PATTERNS):
        return "test"
    return "unclassified"


# --- PR model ---------------------------------------------------------------------------------

@dataclass
class PR:
    number: int
    changed_files: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    base_branch: str = ""
    head_branch: str = ""
    milestone_alignment: str = "none"  # "direct" | "referenced" | "none"
    created_at: Optional[str] = None
    dependency_bumps: list[str] = field(default_factory=list)
    coderabbit_approved: bool = False
    unresolved_review_threads: int = 0
    touches_failing_gate_path: bool = False

    @property
    def age_days(self) -> float:
        if not self.created_at:
            return 0.0
        try:
            created = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        except ValueError:
            return 0.0
        return max(0.0, (datetime.now(timezone.utc) - created).total_seconds() / 86400.0)

    @property
    def size(self) -> int:
        return len(self.changed_files)

    def is_generated_input(self) -> bool:
        return (GENERATED_INPUT_DEPENDENCY_MODULE in self.dependency_bumps
                or any(classify_file(f) == "generated_input" for f in self.changed_files))

    def is_generated_output_toucher(self) -> bool:
        return any(classify_file(f) == "generated" for f in self.changed_files)

    def is_review_ready(self) -> bool:
        return self.coderabbit_approved and self.unresolved_review_threads == 0


def pr_from_dict(d: dict) -> PR:
    return PR(
        number=int(d["number"]),
        changed_files=list(d.get("changed_files") or []),
        labels=list(d.get("labels") or []),
        base_branch=str(d.get("base_branch") or ""),
        head_branch=str(d.get("head_branch") or ""),
        milestone_alignment=str(d.get("milestone_alignment") or "none"),
        created_at=d.get("created_at"),
        dependency_bumps=list(d.get("dependency_bumps") or []),
        coderabbit_approved=bool(d.get("coderabbit_approved", False)),
        unresolved_review_threads=int(d.get("unresolved_review_threads", 0)),
        touches_failing_gate_path=bool(d.get("touches_failing_gate_path", False)),
    )


# --- hard-edge graph ----------------------------------------------------------------------

def build_mechanical_edges(prs: list[PR], repo_default_branch: str) -> tuple[list[tuple[int, int]], list[dict]]:
    """Edges this module can derive purely from provided metadata (no diff-reading needed):
    stacked branches, and generated-input-before-output. Returns (edges, unresolved_notes) —
    an edge is (before, after); unresolved_notes covers pairs with no derivable direction."""
    edges: list[tuple[int, int]] = []
    unresolved: list[dict] = []
    by_head = {p.head_branch: p for p in prs if p.head_branch}

    for p in prs:
        # Stacked: base is another candidate's head, and not the repo default branch.
        if p.base_branch and p.base_branch != repo_default_branch and p.base_branch in by_head:
            base_pr = by_head[p.base_branch]
            if base_pr.number != p.number:
                edges.append((base_pr.number, p.number))

    input_only = [p for p in prs if p.is_generated_input() and not p.is_generated_output_toucher()]
    output_touchers = [p for p in prs if p.is_generated_output_toucher()]
    both_input = [p for p in prs if p.is_generated_input() and p.is_generated_output_toucher()]

    for a in input_only:
        for b in output_touchers:
            if a.number != b.number:
                edges.append((a.number, b.number))

    # Two candidates that both touch a generated-file input feed the same regenerated output
    # with no derivable order between them — flag for a human rather than guessing.
    all_inputs = input_only + both_input
    for i, a in enumerate(all_inputs):
        for b in all_inputs[i + 1:]:
            unresolved.append({
                "prs": [a.number, b.number],
                "why": "both touch a generated-file input (or a github.com/kyverno/api bump) "
                       "feeding the same regenerated output, with no derivable order between them",
            })

    return edges, unresolved


def apply_bypass_pins(prs: list[PR], edges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """e2e-gate-bypass PRs go first, unconditionally: a hard edge from every bypass PR to every
    non-bypass PR."""
    bypass = [p.number for p in prs if "e2e-gate-bypass" in p.labels]
    if not bypass:
        return edges
    others = [p.number for p in prs if p.number not in bypass]
    return edges + [(b, o) for b in bypass for o in others]


# --- cycle detection (Kahn's algorithm) -----------------------------------------------------

def find_cycles_and_acyclic_order_candidates(
    numbers: list[int], edges: list[tuple[int, int]]
) -> tuple[list[int], list[int]]:
    """Returns (acyclic_numbers, cyclic_numbers). Numbers left with unresolved in-degree after
    Kahn's algorithm drains everything it can are part of a cycle."""
    indeg = {n: 0 for n in numbers}
    succ: dict[int, list[int]] = {n: [] for n in numbers}
    for a, b in edges:
        if a in succ and b in indeg:
            succ[a].append(b)
            indeg[b] += 1

    queue = [n for n in numbers if indeg[n] == 0]
    seen: list[int] = []
    indeg = dict(indeg)
    while queue:
        n = queue.pop(0)
        seen.append(n)
        for m in succ[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                queue.append(m)

    seen_set = set(seen)
    cyclic = [n for n in numbers if n not in seen_set]
    return seen, cyclic


# --- weighted priority (soft factors) -------------------------------------------------------

W_MILESTONE_DIRECT = 5.0
W_MILESTONE_REFERENCED = 2.0
W_AGE_PER_DAY = 0.15
W_SIZE = 3.0          # divided by (1 + size): smaller PRs score higher
W_GATE_RISK = 4.0     # subtracted: push risky-while-red PRs later
W_REVIEW_READY = 2.5  # added: CodeRabbit-approved + zero unresolved threads goes earlier


def priority_weight(p: PR, gate_open: bool) -> float:
    """Higher = should rank earlier. Used as the linear coefficient on `rank` in the
    minimize-weighted-completion-time objective (higher-weight items are pushed to low ranks)."""
    milestone_score = {"direct": W_MILESTONE_DIRECT, "referenced": W_MILESTONE_REFERENCED}.get(
        p.milestone_alignment, 0.0
    )
    score = milestone_score + W_AGE_PER_DAY * p.age_days + W_SIZE / (1 + p.size)
    if gate_open and p.touches_failing_gate_path:
        score -= W_GATE_RISK
    if p.is_review_ready():
        score += W_REVIEW_READY
    return score


# --- solve: CP-SAT with a stdlib greedy fallback --------------------------------------------

def _solve_cp_sat(prs: list[PR], edges: list[tuple[int, int]], weights: dict[int, float]) -> Optional[list[int]]:
    try:
        from ortools.sat.python import cp_model
    except ImportError:
        return None

    n = len(prs)
    if n == 0:
        return []
    model = cp_model.CpModel()
    idx = {p.number: i for i, p in enumerate(prs)}
    rank = [model.NewIntVar(0, n - 1, f"rank_{p.number}") for p in prs]
    model.AddAllDifferent(rank)
    for a, b in edges:
        if a in idx and b in idx:
            model.Add(rank[idx[a]] < rank[idx[b]])

    # Scale float weights to integers for CP-SAT's linear objective.
    scaled = {num: int(round(w * 1000)) for num, w in weights.items()}
    model.Minimize(sum(scaled[p.number] * rank[idx[p.number]] for p in prs))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    ordered = sorted(prs, key=lambda p: solver.Value(rank[idx[p.number]]))
    return [p.number for p in ordered]


def _solve_greedy(prs: list[PR], edges: list[tuple[int, int]], weights: dict[int, float]) -> list[int]:
    """Weighted priority-list scheduling: at each step, among precedence-satisfied PRs, pick
    the highest-weight one. Deterministic; not guaranteed globally optimal for the weighted
    objective (that's what the CP-SAT path is for), but a real weighted blend, not a
    lexicographic rule."""
    numbers = [p.number for p in prs]
    indeg = {n: 0 for n in numbers}
    succ: dict[int, list[int]] = {n: [] for n in numbers}
    for a, b in edges:
        if a in indeg and b in indeg:
            succ[a].append(b)
            indeg[b] += 1

    available = [n for n in numbers if indeg[n] == 0]
    order: list[int] = []
    remaining_indeg = dict(indeg)
    while available:
        available.sort(key=lambda n: (-weights[n], n))
        chosen = available.pop(0)
        order.append(chosen)
        for m in succ[chosen]:
            remaining_indeg[m] -= 1
            if remaining_indeg[m] == 0:
                available.append(m)
    return order


# --- top-level entry point -------------------------------------------------------------------

def sequence(
    pr_dicts: list[dict],
    precedence_hints: Optional[list[dict]] = None,
    repo_default_branch: str = "main",
    gate_open: bool = False,
) -> dict[str, Any]:
    prs = [pr_from_dict(d) for d in pr_dicts]
    numbers = [p.number for p in prs]
    by_number = {p.number: p for p in prs}

    mech_edges, unresolved = build_mechanical_edges(prs, repo_default_branch)
    hint_edges = []
    for hint in (precedence_hints or []):
        before, after = hint.get("before"), hint.get("after")
        if before in by_number and after in by_number:
            hint_edges.append((before, after))
    edges = apply_bypass_pins(prs, mech_edges + hint_edges)

    acyclic, cyclic = find_cycles_and_acyclic_order_candidates(numbers, edges)
    cyclic_set = set(cyclic)
    solved_prs = [p for p in prs if p.number not in cyclic_set]
    solved_edges = [(a, b) for a, b in edges if a not in cyclic_set and b not in cyclic_set]

    weights = {p.number: priority_weight(p, gate_open) for p in solved_prs}
    order = _solve_cp_sat(solved_prs, solved_edges, weights)
    solver_used = "cp-sat"
    if order is None:
        order = _solve_greedy(solved_prs, solved_edges, weights)
        solver_used = "greedy-fallback"

    bypass_numbers = {p.number for p in prs if "e2e-gate-bypass" in p.labels}

    sequence_out = []
    for position, number in enumerate(order, start=1):
        p = by_number[number]
        reasons = []
        if number in bypass_numbers:
            reasons.append("carries e2e-gate-bypass — placed first unconditionally")
        preds = [a for a, b in solved_edges if b == number]
        bypass_preds = [a for a in preds if a in bypass_numbers]
        other_preds = [a for a in preds if a not in bypass_numbers]
        if bypass_preds:
            reasons.append(f"must follow e2e-gate-bypass PR(s) {bypass_preds}")
        if other_preds:
            kinds = "stacked/generated-file" if any((a, number) in mech_edges for a in other_preds) else "precedence hint"
            reasons.append(f"must follow PR(s) {other_preds} ({kinds})")
        if p.milestone_alignment == "direct":
            reasons.append("closes the target milestone issue directly")
        elif p.milestone_alignment == "referenced":
            reasons.append("closes an issue the milestone issue references")
        if p.is_review_ready():
            reasons.append("CodeRabbit-approved with no unresolved review threads")
        if gate_open and p.touches_failing_gate_path:
            reasons.append("touches a path the open e2e-gate failure names — elevated risk")
        if not reasons:
            reasons.append(f"age tiebreak ({p.age_days:.1f} days open)")

        warnings = []
        if gate_open and p.touches_failing_gate_path and number not in bypass_numbers:
            warnings.append("e2e-gate is open and this PR touches an implicated path")

        sequence_out.append({
            "position": position,
            "pr": number,
            "reason": "; ".join(reasons),
            "risk": "elevated" if (gate_open and p.touches_failing_gate_path) else "normal",
            "warnings": warnings,
        })

    return {
        "sequence": sequence_out,
        "cycles": [cyclic] if cyclic else [],
        "unresolved": unresolved,
        "gate_status": {"open": gate_open},
        "solver": solver_used,
    }
