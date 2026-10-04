"""kyverno-fetch plugin — one-call GraphQL PR-candidate fetch for pr-queue, plus an on-demand
diff-overlap check."""

from __future__ import annotations

from .tools import (
    FETCH_FILE_DIFF_OVERLAP_SCHEMA,
    FETCH_PR_CANDIDATES_SCHEMA,
    handle_fetch_file_diff_overlap,
    handle_fetch_pr_candidates,
)


def register(ctx) -> None:
    ctx.register_tool(
        name="fetch_pr_candidates",
        toolset="kyverno-fetch",
        schema=FETCH_PR_CANDIDATES_SCHEMA,
        handler=handle_fetch_pr_candidates,
        description="One-call GraphQL fetch of every candidate PR's full metadata.",
        emoji="📡",
    )
    ctx.register_tool(
        name="fetch_file_diff_overlap",
        toolset="kyverno-fetch",
        schema=FETCH_FILE_DIFF_OVERLAP_SCHEMA,
        handler=handle_fetch_file_diff_overlap,
        description="Checks whether two PRs touching the same file touch the same lines.",
        emoji="🔬",
    )
