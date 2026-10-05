"""Tool schema + handler for `fetch_pr_candidates`. One call replaces pr-queue's old
search_pull_requests + one pull_request_read per PR sequence."""

from __future__ import annotations

import json
from typing import Any, Dict

from .fetch import FetchError, fetch_file_diff_overlap, fetch_pr_candidates


def _schema(name: str, description: str, properties: Dict[str, Any], required=None) -> Dict[str, Any]:
    params: Dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        params["required"] = required
    return {"name": name, "description": description, "parameters": params}


FETCH_PR_CANDIDATES_SCHEMA = _schema(
    "fetch_pr_candidates",
    "Fetch every candidate PR's full metadata in one call via GitHub's GraphQL API directly "
    "(the profile's own GITHUB_TOKEN, same scopes already granted to the github MCP server) — "
    "replaces a search_pull_requests + one pull_request_read per PR sequence with a single "
    "tool invocation. Returns, per PR: title, url, body, author, author_association "
    "(OWNER/MEMBER/COLLABORATOR/CONTRIBUTOR/FIRST_TIME_CONTRIBUTOR/NONE — cite this, a "
    "first-time contributor's PR generally warrants a closer look), created_at, base/head "
    "branch, size (files/additions/deletions — a review-effort signal, distinct from "
    "priority), milestone, milestone_due_on (cite when close — real urgency, not a guess), "
    "labels, changed_files, unresolved_review_threads, "
    "coderabbit_approved, ci_state (the PR's own checks only, excluding the E2E Gate "
    "status — see gate_blocked for that), closing_issues (each with its own milestone, "
    "whether it's open, and its own labels — release-* lives here, not on the PR), and "
    "external_references: for a body reference ('Parent: #N', 'Depends on #N', ...) to a "
    "number outside this fetched set, its real kind/state/title. Cite that directly; never "
    "tell the maintainer to go check it themselves. Also per PR: is_dependabot, merge_state "
    "(GitHub's mergeStateStatus: CLEAN/BLOCKED/UNSTABLE/DIRTY/BEHIND), and copilot_review "
    "(Copilot's latest verdict heading, whether it is the approving '🟢 Approved', its one-line "
    "summary and finding count; null if Copilot hasn't reviewed). For a Dependabot PR: bumps "
    "(each dependency's name/from/to/update_type/group, read from the commit trailers) and "
    "semver_level (major/minor/patch, or unknown if any entry is unrecognized — the same rule "
    "the triage workflow uses, so it is available before that workflow has labelled the PR). "
    "Pass changed_files/labels/base_branch/"
    "head_branch/body/dependency_bumps and each closing issue's number into sequence_prs; "
    "everything else stays with you for citing when ordering within a tier.",
    {
        "repo": {"type": "string", "description": "'owner/repo', e.g. 'kyverno/kyverno'."},
        "search_query": {
            "type": "string",
            "description": "Extra GitHub search qualifiers beyond 'repo:/is:pr/is:open/"
            "draft:false', which this tool adds itself — e.g. 'label:ready-for-review', "
            "'label:ready-for-review milestone:\"Kyverno Release 1.20.0\"', "
            "'label:needs-review', 'label:workflow-approval-required', 'author:someuser', "
            "'author:app/dependabot' (every open Dependabot PR, labelled or not).",
        },
        "limit": {
            "type": "integer",
            "description": "Max PRs to fetch full detail for (default 15). total_count in "
            "the result is the real total match count, accurate even when truncated.",
        },
    },
    required=["repo", "search_query"],
)


def handle_fetch_pr_candidates(args: Dict[str, Any], **_kw) -> str:
    repo = args.get("repo")
    search_query = args.get("search_query")
    if not repo or not search_query:
        return json.dumps({"success": False, "error": "repo and search_query are required"})
    try:
        result = fetch_pr_candidates(
            repo=str(repo),
            search_query=str(search_query),
            limit=int(args.get("limit") or 15),
        )
    except FetchError as exc:
        return json.dumps({"success": False, "error": str(exc)})
    return json.dumps({"success": True, **result})


FETCH_FILE_DIFF_OVERLAP_SCHEMA = _schema(
    "fetch_file_diff_overlap",
    "On-demand follow-up for a file_overlaps entry from sequence_prs: fetches each listed "
    "PR's real diff hunks for one specific file. Returns raw patches only, no computed "
    "verdict — each PR's hunk line numbers are relative to its own merge-base with main, "
    "which can differ between PRs, so comparing line numbers across PRs isn't reliable. "
    "Read the patches yourself and describe what each change actually does and whether they "
    "genuinely interact. Only call this for a file_overlaps pair worth the extra look, not "
    "for every one automatically.",
    {
        "repo": {"type": "string", "description": "'owner/repo'."},
        "path": {"type": "string", "description": "The exact file path both PRs changed."},
        "pr_numbers": {"type": "array", "items": {"type": "integer"},
                        "description": "The PRs to compare (usually 2, from one file_overlaps entry)."},
    },
    required=["repo", "path", "pr_numbers"],
)


def handle_fetch_file_diff_overlap(args: Dict[str, Any], **_kw) -> str:
    repo = args.get("repo")
    path = args.get("path")
    pr_numbers = args.get("pr_numbers") or []
    if not repo or not path or not pr_numbers:
        return json.dumps({"success": False, "error": "repo, path, and pr_numbers are required"})
    try:
        result = fetch_file_diff_overlap(repo=str(repo), path=str(path), pr_numbers=[int(n) for n in pr_numbers])
    except FetchError as exc:
        return json.dumps({"success": False, "error": str(exc)})
    return json.dumps({"success": True, **result})
