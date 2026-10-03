"""Tool schema + handler for `fetch_pr_candidates`. One call replaces pr-queue's old
search_pull_requests + one pull_request_read per PR sequence."""

from __future__ import annotations

import json
from typing import Any, Dict

from .fetch import FetchError, fetch_pr_candidates


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
    "tool invocation. Returns, per PR: title, url, body, author, created_at, base/head "
    "branch, milestone, labels, changed_files, unresolved_review_threads, "
    "coderabbit_approved, ci_state, and closing_issues (each with its own milestone, "
    "whether that milestone is open, and its own labels — release-critical/-high/-medium/"
    "-low live on the issue, never the PR itself, see kyverno-context). Pass this PR's "
    "changed_files/labels/base_branch/head_branch/body/dependency_bumps and each closing "
    "issue's number (not the whole object) into sequence_prs; release-priority and "
    "milestone stay with you for citing when ordering within a tier.",
    {
        "repo": {"type": "string", "description": "'owner/repo', e.g. 'kyverno/kyverno'."},
        "search_query": {
            "type": "string",
            "description": "Extra GitHub search qualifiers beyond 'repo:/is:pr/is:open/"
            "draft:false', which this tool adds itself — e.g. 'label:ready-for-review', "
            "'label:ready-for-review milestone:\"Kyverno Release 1.20.0\"', "
            "'label:needs-review', 'label:workflow-approval-required', 'author:someuser'.",
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
