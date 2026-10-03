"""GraphQL fetch for pr-queue — stdlib only, one tool call replaces N sequential
pull_request_read calls.

Two real network passes per call: a search query to resolve candidate PR numbers (mirrors
pr-readiness-check.yaml's own lightweight search step), then a detail query per number, run
concurrently via a thread pool (stdlib `concurrent.futures` — no new dependency). Both talk to
GitHub's GraphQL API directly with the profile's own GITHUB_TOKEN (same scopes already granted
to the github MCP server) — the model sees one tool call regardless of how many real HTTP
requests happen inside it.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import urllib.error
import urllib.request
from typing import Any

_GRAPHQL_URL = "https://api.github.com/graphql"
_USER_AGENT = "kyverno-assistant-fetch-plugin"


class FetchError(RuntimeError):
    pass


def _token() -> str:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise FetchError("GITHUB_TOKEN not set in this profile's environment")
    return token


def _graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        _GRAPHQL_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {_token()}",
            "Content-Type": "application/json",
            "User-Agent": _USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise FetchError(f"GitHub GraphQL HTTP {exc.code}: {detail}") from exc
    if payload.get("errors"):
        raise FetchError(f"GitHub GraphQL error: {payload['errors']}")
    return payload["data"]


_SEARCH_QUERY = """
query($search: String!, $first: Int!) {
  search(query: $search, type: ISSUE, first: $first) {
    issueCount
    nodes { ... on PullRequest { number } }
  }
}
"""

# Field shape mirrors .github/workflows/pr-readiness-check.yaml's own detail_query — that
# workflow already proves this shape works at scale against this repo. hasNextPage on each
# >100-item connection is surfaced as a *_truncated flag rather than fully paginated here —
# true for an occasional huge PR, not worth the extra round trips for the common case.
_DETAIL_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      number
      title
      url
      body
      author { login }
      createdAt
      baseRefName
      headRefName
      milestone { title }
      labels(first: 100) { pageInfo { hasNextPage } nodes { name } }
      files(first: 100) { pageInfo { hasNextPage } nodes { path } }
      reviewThreads(first: 100) { pageInfo { hasNextPage } nodes { isResolved } }
      reviews(last: 50) { nodes { author { login } state } }
      commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }
      closingIssuesReferences(first: 20) {
        nodes { number milestone { title state } labels(first: 20) { nodes { name } } }
      }
    }
  }
}
"""


def _fetch_one(owner: str, name: str, number: int) -> dict[str, Any]:
    data = _graphql(_DETAIL_QUERY, {"owner": owner, "name": name, "number": number})
    pr = data["repository"]["pullRequest"]
    if pr is None:
        return {"number": number, "error": "not found (closed or renumbered mid-fetch?)"}

    threads = pr["reviewThreads"]["nodes"]
    reviews = pr["reviews"]["nodes"]
    # CodeRabbit shows up as a real review author; this is the only way to read its verdict
    # via GraphQL (there's no separate "bot verdict" field).
    coderabbit_approved = any(
        r["author"] and r["author"]["login"] == "coderabbitai[bot]" and r["state"] == "APPROVED"
        for r in reviews
    )
    commit_nodes = pr["commits"]["nodes"]
    rollup = (commit_nodes[0]["commit"]["statusCheckRollup"] or {}) if commit_nodes else {}

    return {
        "number": pr["number"],
        "title": pr["title"],
        "url": pr["url"],
        "body": pr["body"] or "",
        "author": (pr["author"] or {}).get("login"),
        "created_at": pr["createdAt"],
        "base_branch": pr["baseRefName"],
        "head_branch": pr["headRefName"],
        "milestone": (pr["milestone"] or {}).get("title"),
        "labels": [n["name"] for n in pr["labels"]["nodes"]],
        "labels_truncated": pr["labels"]["pageInfo"]["hasNextPage"],
        "changed_files": [n["path"] for n in pr["files"]["nodes"]],
        "files_truncated": pr["files"]["pageInfo"]["hasNextPage"],
        "unresolved_review_threads": sum(1 for t in threads if not t["isResolved"]),
        "review_threads_truncated": pr["reviewThreads"]["pageInfo"]["hasNextPage"],
        "coderabbit_approved": coderabbit_approved,
        "ci_state": rollup.get("state"),
        "closing_issues": [
            {
                "number": n["number"],
                "milestone": (n["milestone"] or {}).get("title"),
                "milestone_open": bool(n["milestone"] and n["milestone"]["state"] == "OPEN"),
                # release-critical/-high/-medium/-low live here, on the issue — never on the
                # PR itself, and not applied/removed by any workflow (a maintainer judgment
                # call, not automation) — see kyverno-context's label-taxonomy reference.
                "labels": [l["name"] for l in n["labels"]["nodes"]],
            }
            for n in pr["closingIssuesReferences"]["nodes"]
        ],
    }


def fetch_pr_candidates(repo: str, search_query: str, limit: int = 15) -> dict[str, Any]:
    if "/" not in repo:
        raise FetchError(f"repo must be 'owner/name', got {repo!r}")
    owner, name = repo.split("/", 1)

    full_search = f"repo:{repo} is:pr is:open draft:false {search_query}".strip()
    search_data = _graphql(_SEARCH_QUERY, {"search": full_search, "first": min(limit, 100)})
    search_result = search_data["search"]
    numbers = [n["number"] for n in search_result["nodes"] if n]
    total_count = search_result["issueCount"]

    prs: list[dict[str, Any]] = []
    errors: list[str] = []
    if numbers:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(numbers))) as pool:
            futures = {pool.submit(_fetch_one, owner, name, n): n for n in numbers}
            for future in concurrent.futures.as_completed(futures):
                n = futures[future]
                try:
                    prs.append(future.result())
                except FetchError as exc:
                    errors.append(f"PR #{n}: {exc}")

    prs.sort(key=lambda p: p.get("number", 0))
    return {
        "total_count": total_count,
        "fetched": len(prs),
        "truncated": total_count > len(prs),
        "prs": prs,
        "errors": errors,
    }
