# Dependabot test fixture

Not part of kyctrl. Exists solely to give the `gomod` ecosystem real,
outdated dependencies (`google/uuid` pinned to `v1.1.0`, `google/go-cmp`
pinned to `v0.5.9`) so Dependabot opens real PRs against this repo, which
is what `.github/workflows/dependabot-autofix.yml` needs to react to.
`main_test.go` exists so a bump can break `go test`, not just `go
build`/`go vet` — a different failure category from the syntax errors
used to test the build/vet path.
See `docs/testing-copilot-dependabot-autofix.md` for the test plan.
