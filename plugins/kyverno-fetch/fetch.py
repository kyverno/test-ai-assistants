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
import re
import urllib.error
import urllib.request
from typing import Any, Optional

_GRAPHQL_URL = "https://api.github.com/graphql"
_USER_AGENT = "kyverno-assistant-fetch-plugin"

# Mirror of kyverno-sequencer/sequencer.py's _CROSS_REF_PATTERN — kept in sync manually.
# Covers real phrasing variants, not just the canonical form: "Parent: #17701", "Stacks on
# top of #17695", "depends on kyverno/kyverno#17720", "Blocked by #N".
_CROSS_REF_PATTERN = re.compile(
    r"\b(?:depends on|blocked by|requires|stack(?:s|ed)?\s+on(?:\s+top\s+of)?|parent)\b"
    r"\s*:?\s*(?:[\w.-]+/[\w.-]+)?#(\d+)",
    re.IGNORECASE,
)


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


def _rest_get(path: str) -> Any:
    req = urllib.request.Request(
        f"https://api.github.com/{path}",
        headers={
            "Authorization": f"Bearer {_token()}",
            "Accept": "application/vnd.github+json",
            "User-Agent": _USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise FetchError(f"GitHub REST HTTP {exc.code}: {detail}") from exc


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
      authorAssociation
      createdAt
      baseRefName
      headRefName
      additions
      deletions
      changedFiles
      milestone { title dueOn }
      labels(first: 100) { pageInfo { hasNextPage } nodes { name } }
      files(first: 100) { pageInfo { hasNextPage } nodes { path } }
      reviewThreads(first: 100) { pageInfo { hasNextPage } nodes { isResolved } }
      reviews(last: 50) { nodes { author { login } state } }
      commits(last: 1) { nodes { commit {
        statusCheckRollup {
          contexts(first: 100) {
            pageInfo { hasNextPage }
            nodes {
              __typename
              ... on CheckRun { name conclusion status }
              ... on StatusContext { context state }
            }
          }
        }
      } } }
      closingIssuesReferences(first: 20) {
        nodes { number milestone { title state } labels(first: 20) { nodes { name } } }
      }
    }
  }
}
"""


def _compute_ci_state(contexts: list[dict]) -> str:
    """statusCheckRollup's own single .state field can't be trusted: it blends the 'E2E Gate'
    status context (the branch-wide gate, already surfaced separately via gate_blocked) in
    with the PR's own checks, so a gated PR shows FAILURE here even when every real check is
    green. Exclude that one context and derive the real state from what's left."""
    relevant = [c for c in contexts if c.get("context") != "E2E Gate"]
    if not relevant:
        return "UNKNOWN"
    has_failure = False
    has_pending = False
    for c in relevant:
        if c.get("__typename") == "CheckRun":
            if c.get("status") != "COMPLETED":
                has_pending = True
            elif c.get("conclusion") not in ("SUCCESS", "NEUTRAL", "SKIPPED"):
                has_failure = True
        else:  # StatusContext
            state = c.get("state")
            if state == "PENDING":
                has_pending = True
            elif state != "SUCCESS":
                has_failure = True
    if has_failure:
        return "FAILURE"
    if has_pending:
        return "PENDING"
    return "SUCCESS"


def _fetch_one(owner: str, name: str, number: int) -> dict[str, Any]:
    data = _graphql(_DETAIL_QUERY, {"owner": owner, "name": name, "number": number})
    pr = data["repository"]["pullRequest"]
    if pr is None:
        return {"number": number, "error": "not found (closed or renumbered mid-fetch?)"}

    threads = pr["reviewThreads"]["nodes"]
    reviews = pr["reviews"]["nodes"]
    # CodeRabbit's real GraphQL author.login is "coderabbitai" (no "[bot]" suffix — that's a
    # REST/UI-only convention; GraphQL's Bot actor doesn't carry it).
    coderabbit_approved = any(
        r["author"] and r["author"]["login"] == "coderabbitai" and r["state"] == "APPROVED"
        for r in reviews
    )
    commit_nodes = pr["commits"]["nodes"]
    rollup = (commit_nodes[0]["commit"]["statusCheckRollup"] or {}) if commit_nodes else {}
    contexts_conn = rollup.get("contexts") or {"nodes": [], "pageInfo": {"hasNextPage": False}}

    return {
        "number": pr["number"],
        "title": pr["title"],
        "url": pr["url"],
        "body": pr["body"] or "",
        "author": (pr["author"] or {}).get("login"),
        "author_association": pr["authorAssociation"],
        "created_at": pr["createdAt"],
        "base_branch": pr["baseRefName"],
        "head_branch": pr["headRefName"],
        "size": {"files": pr["changedFiles"], "additions": pr["additions"], "deletions": pr["deletions"]},
        "milestone": (pr["milestone"] or {}).get("title"),
        "milestone_due_on": (pr["milestone"] or {}).get("dueOn"),
        "labels": [n["name"] for n in pr["labels"]["nodes"]],
        "labels_truncated": pr["labels"]["pageInfo"]["hasNextPage"],
        "changed_files": [n["path"] for n in pr["files"]["nodes"]],
        "files_truncated": pr["files"]["pageInfo"]["hasNextPage"],
        "unresolved_review_threads": sum(1 for t in threads if not t["isResolved"]),
        "review_threads_truncated": pr["reviewThreads"]["pageInfo"]["hasNextPage"],
        "coderabbit_approved": coderabbit_approved,
        "ci_state": _compute_ci_state(contexts_conn["nodes"]),
        "ci_state_truncated": contexts_conn["pageInfo"]["hasNextPage"],
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


# A body reference ("Parent: #N") may name an issue, not a PR — GitHub shares one number
# sequence between them. issueOrPullRequest resolves either without erroring on a type
# mismatch the way a plain pullRequest(number:) field does.
_REF_STATE_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issueOrPullRequest(number: $number) {
      __typename
      ... on Issue { number title state }
      ... on PullRequest { number title state }
    }
  }
}
"""


def _resolve_ref_state(owner: str, name: str, number: int) -> dict[str, Any]:
    data = _graphql(_REF_STATE_QUERY, {"owner": owner, "name": name, "number": number})
    node = data["repository"]["issueOrPullRequest"]
    if node is None:
        return {"number": number, "kind": "unknown", "state": "NOT_FOUND", "title": None}
    kind = "pr" if node["__typename"] == "PullRequest" else "issue"
    return {"number": node["number"], "kind": kind, "state": node["state"], "title": node["title"]}


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

    # A PR's body can reference another PR ("Depends on #N", "Parent: #N", "Stacks on top of
    # #N") that isn't in this fetched set — stale/already-merged, or just outside the slice.
    # Resolve each unique one's real state in this same call instead of leaving it as a
    # "please go check" note.
    fetched_numbers = {p["number"] for p in prs if "number" in p}
    refs_by_pr: dict[int, set[int]] = {}
    for p in prs:
        refs = {int(m) for m in _CROSS_REF_PATTERN.findall(p.get("body") or "")}
        external = {r for r in refs if r not in fetched_numbers and r != p["number"]}
        if external:
            refs_by_pr[p["number"]] = external

    if refs_by_pr:
        unique_external = {r for refs in refs_by_pr.values() for r in refs}
        resolved: dict[int, dict[str, Any]] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(unique_external))) as pool:
            futures = {pool.submit(_resolve_ref_state, owner, name, n): n for n in unique_external}
            for future in concurrent.futures.as_completed(futures):
                n = futures[future]
                try:
                    resolved[n] = future.result()
                except FetchError as exc:
                    resolved[n] = {"number": n, "state": "UNKNOWN", "title": None, "error": str(exc)}
        for p in prs:
            if p["number"] in refs_by_pr:
                p["external_references"] = [resolved[n] for n in sorted(refs_by_pr[p["number"]])]

    prs.sort(key=lambda p: p.get("number", 0))
    return {
        "total_count": total_count,
        "fetched": len(prs),
        "truncated": total_count > len(prs),
        "prs": prs,
        "errors": errors,
    }


def _get_patch_for_file(owner: str, name: str, number: int, path: str) -> Optional[str]:
    page = 1
    while page <= 5:  # 500 files; a PR touching more than that needs a human regardless
        files = _rest_get(f"repos/{owner}/{name}/pulls/{number}/files?per_page=100&page={page}")
        for f in files:
            if f.get("filename") == path:
                return f.get("patch")  # absent for binary/very large files
        if len(files) < 100:
            return None
        page += 1
    return None


def fetch_file_diff_overlap(repo: str, path: str, pr_numbers: list[int]) -> dict[str, Any]:
    """Real diff hunks each listed PR has for one specific file (REST — GraphQL has no patch
    field). Deliberately returns raw patches only, no computed overlap verdict: each PR's
    hunk line numbers are expressed against its own merge-base with main, which can differ
    between PRs, so comparing line ranges across PRs can't be made reliable — reading what
    each patch actually does is the real check, not a number."""
    if "/" not in repo:
        raise FetchError(f"repo must be 'owner/name', got {repo!r}")
    owner, name = repo.split("/", 1)

    by_pr: dict[int, Optional[str]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(pr_numbers))) as pool:
        futures = {pool.submit(_get_patch_for_file, owner, name, n, path): n for n in pr_numbers}
        for future in concurrent.futures.as_completed(futures):
            by_pr[futures[future]] = future.result()

    return {"path": path, "by_pr": by_pr}
