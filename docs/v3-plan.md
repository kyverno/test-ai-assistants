# v3 plan: pointer only

Not scoped yet. One thing to pick up when this extends beyond one
maintainer on their own laptop to multiple organizations:

- **Run the gateway in Docker instead of on each maintainer's machine.**
  Hermes ships its own `Dockerfile`/`docker-compose.yml` for this
  (`~/.hermes` mounted as a volume, `network_mode: host`) — not something
  we'd build ourselves. Needs the host Docker socket mounted in, since
  Hermes would then be spawning the github/slack MCP containers as
  siblings from inside its own container — verify that's wired before
  relying on it. Not needed while each maintainer runs their own local
  install; becomes relevant once one instance needs to serve multiple
  orgs/maintainers from shared infra.
