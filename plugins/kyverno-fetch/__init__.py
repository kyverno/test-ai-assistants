"""kyverno-fetch plugin — one-call GraphQL PR-candidate fetch for pr-queue."""

from __future__ import annotations

from .tools import FETCH_PR_CANDIDATES_SCHEMA, handle_fetch_pr_candidates


def register(ctx) -> None:
    ctx.register_tool(
        name="fetch_pr_candidates",
        toolset="kyverno-fetch",
        schema=FETCH_PR_CANDIDATES_SCHEMA,
        handler=handle_fetch_pr_candidates,
        description="One-call GraphQL fetch of every candidate PR's full metadata.",
        emoji="📡",
    )
