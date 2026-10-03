# kyverno-fetch

A bundled Hermes plugin, not a skill. Registers one tool, `fetch_pr_candidates`, that
`pr-queue` calls instead of `search_pull_requests` plus one `pull_request_read` per
candidate — the actual fix for a real session that took 15 of 107 PRs, fetched one at a
time, ~5 minutes. The model sees one tool call; this plugin's own Python code makes the
real network requests (a search pass, then one GraphQL detail call per candidate, run
concurrently via a thread pool) directly against `https://api.github.com/graphql`, using
the profile's own `GITHUB_TOKEN` — the same scopes already granted to the `github` MCP
server, no new credential, no MCP server involved for this call.

Ships automatically on `hermes profile install .`, same as `kyverno-sequencer` (see
`docs/architecture.md`). Pure stdlib (`urllib.request`, `concurrent.futures`) — no
external dependency to install.
