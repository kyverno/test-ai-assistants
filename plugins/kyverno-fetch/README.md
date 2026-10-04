# kyverno-fetch

A bundled Hermes plugin, not a skill. Registers two tools:

- `fetch_pr_candidates` — what `pr-queue` calls instead of `search_pull_requests` plus one
  `pull_request_read` per candidate — the actual fix for a real session that took 15 of 107
  PRs, fetched one at a time, ~5 minutes. The model sees one tool call; this plugin's own
  Python code makes the real network requests (a search pass, then one GraphQL detail call
  per candidate, run concurrently via a thread pool) directly against
  `https://api.github.com/graphql`.
- `fetch_file_diff_overlap` — an on-demand follow-up: two PRs touching the same file doesn't
  mean they touch the same lines. Fetches each PR's real diff hunks for one file via REST
  (GraphQL has no patch field) and checks whether the touched line ranges actually overlap.

Both use the profile's own `GITHUB_TOKEN` — the same scopes already granted to the `github`
MCP server, no new credential, no MCP server involved for either call.

Ships automatically on `hermes profile install .`, same as `kyverno-sequencer` (see
`docs/architecture.md`). Pure stdlib (`urllib.request`, `concurrent.futures`) — no
external dependency to install.
