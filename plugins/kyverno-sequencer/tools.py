"""Tool schema + handler for `sequence_prs`. Thin: parse args, call sequencer.sequence, return
JSON. No GitHub/Slack access here — pr-queue fetches everything and passes it in."""

from __future__ import annotations

import json
from typing import Any, Dict

from . import sequencer


def _str(description: str) -> Dict[str, Any]:
    return {"type": "string", "description": description}


def _schema(name: str, description: str, properties: Dict[str, Any], required=None) -> Dict[str, Any]:
    params: Dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        params["required"] = required
    params["additionalProperties"] = False
    return {"name": name, "description": description, "parameters": params}


_PR_ITEM_SCHEMA = {
    "type": "object",
    "description": "One candidate PR's already-fetched metadata.",
    "properties": {
        "number": {"type": "integer", "description": "PR number."},
        "changed_files": {"type": "array", "items": {"type": "string"},
                           "description": "Every changed file path (from get_files)."},
        "labels": {"type": "array", "items": {"type": "string"}},
        "base_branch": _str("PR's base branch name."),
        "head_branch": _str("PR's head branch name."),
        "milestone_alignment": {"type": "string", "enum": ["direct", "referenced", "none"],
                                 "description": "'direct': closes the target milestone issue. "
                                 "'referenced': closes an issue the milestone issue references. "
                                 "'none': neither."},
        "created_at": _str("ISO-8601 creation timestamp, for age tiebreak."),
        "dependency_bumps": {"type": "array", "items": {"type": "string"},
                              "description": "Go module paths this PR bumps (Dependabot PRs). "
                              "A github.com/kyverno/api bump counts as a generated-file-input "
                              "touch even though no api/**/*_types.go path appears in "
                              "changed_files."},
        "coderabbit_approved": {"type": "boolean",
                                 "description": "From get_reviews — CodeRabbit's verdict."},
        "unresolved_review_threads": {"type": "integer",
                                       "description": "Count from get_review_comments's "
                                       "is_resolved field. 0 plus coderabbit_approved=true "
                                       "is this PR's review-readiness signal."},
        "touches_failing_gate_path": {"type": "boolean",
                                       "description": "True if this PR's changed files overlap "
                                       "the paths/packages an open e2e-failure issue names."},
    },
    "required": ["number"],
    "additionalProperties": False,
}

SEQUENCE_PRS_SCHEMA = _schema(
    "sequence_prs",
    "Compute a deterministic candidate merge sequence from already-fetched PR metadata: "
    "file-risk classification, a hard-precedence graph (stacked branches, generated-file "
    "input-before-output mechanically; interface/dependency-usage edges via precedence_hints "
    "you supply, since those need diff-reading judgment this tool doesn't have), cycle "
    "detection, and a weighted CP-SAT rank solve (milestone urgency, age, size, e2e-gate risk, "
    "review-readiness) with a stdlib fallback. Returns a labeled CANDIDATE order, not a verdict "
    "— check it against Slack context, Dependabot diagnosis, and anything else the graph can't "
    "see before presenting it, per pr-queue's Procedure.",
    {
        "prs": {"type": "array", "items": _PR_ITEM_SCHEMA,
                "description": "Every candidate PR (ready-for-review + needs-review)."},
        "precedence_hints": {
            "type": "array",
            "description": "Hard-ordering edges you've already determined from diffs/search_code "
            "(interface definer-before-implementer, dependency-usage) — this tool can't derive "
            "these from file paths alone.",
            "items": {
                "type": "object",
                "properties": {
                    "before": {"type": "integer"},
                    "after": {"type": "integer"},
                    "reason": _str("Why this edge exists — surfaced back in the output."),
                },
                "required": ["before", "after"],
                "additionalProperties": False,
            },
        },
        "repo_default_branch": _str("Repo's default branch (e.g. 'main') — a PR whose base "
                                     "equals this is never 'stacked'."),
        "gate_open": {"type": "boolean",
                      "description": "Whether an e2e-failure issue is currently open for the "
                      "target branch."},
    },
    required=["prs"],
)


def handle_sequence_prs(args: Dict[str, Any], **_kw) -> str:
    prs = args.get("prs") or []
    if not isinstance(prs, list) or not prs:
        return json.dumps({"success": False, "error": "prs must be a non-empty array"})
    try:
        result = sequencer.sequence(
            pr_dicts=prs,
            precedence_hints=args.get("precedence_hints") or [],
            repo_default_branch=str(args.get("repo_default_branch") or "main"),
            gate_open=bool(args.get("gate_open", False)),
        )
    except (KeyError, ValueError, TypeError) as exc:
        return json.dumps({"success": False, "error": f"bad input: {exc}"})
    return json.dumps({"success": True, **result})
