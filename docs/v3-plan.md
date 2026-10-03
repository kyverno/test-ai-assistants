# v3 plan: pointer only

Not scoped yet. Things to pick up later:

- **Run the gateway in Docker instead of on each maintainer's machine.**
  Hermes ships its own `Dockerfile`/`docker-compose.yml` for this
  (`~/.hermes` mounted as a volume, `network_mode: host`) — not something
  we'd build ourselves. Needs the host Docker socket mounted in, since
  Hermes would then be spawning the github/slack MCP containers as
  siblings from inside its own container — verify that's wired before
  relying on it. Not needed while each maintainer runs their own local
  install; becomes relevant once one instance needs to serve multiple
  orgs/maintainers from shared infra.

- **A real dashboard.** Not a claude.ai artifact — that capability doesn't
  exist for Hermes. The real mechanism is Hermes's own local dashboard-
  plugin system (`hermes dashboard`, `localhost:9119`): a plugin ships
  `dashboard/manifest.json` plus a JS bundle to add a tab. Deferred —
  it needs a frontend build step, and its plugin-loading path has a
  documented, patched RCE history, so it deserves its own careful pass
  rather than being folded into this one.

- **`gopls` MCP integration for real interface/call-graph edges.** The
  sequencer's hard-edge detection is deliberately limited to what's
  mechanically derivable (stacked branches, generated-file ordering,
  explicit body references, closing-issue conflicts) — it doesn't try to
  approximate "which PR's diff implies which other PR must come first"
  from a text search. A `gopls`-backed MCP server would give `sequence_prs`
  a real semantic edge type for that, on top of the tiered graph this pass
  built. Build after the current four are tested in real use.
