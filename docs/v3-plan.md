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


# to fix:
  1. CODEOWNERS / "is the maintainer actually a requested reviewer" is never used. kyverno-context resolves this, but
     pr-queue's procedure never calls it. For a personal assistant, "is this even mine to review" seems like it should matter,
     and right now it doesn't factor in at all.
  3. The security/code-scanning/Dependabot alert tools are granted but never called anywhere in the Procedure. Same story —
     listed as available, zero instructions on when to actually use them.
     we also want to see the securities and vulnerabilities posted , see their criticalities, should we raise any issues for the same, should we fix , and we should ammend the agents.md files maybe in kyverno to flag them , and maybe we should add some instructions for coderabbit to flag it as well
# Semantic PR Intelligence: What Actually Works for Go

The ecosystem for semantic Go PR analysis is fragmented but has several genuinely useful layers, and the honest answer is this: **you can get meaningful semantic signal today without waiting for a perfect tool**, by combining two or three readily available components — but the "holy grail" of fully automated semantic conflict detection between arbitrary PRs doesn't exist yet as a turnkey solution. The best immediately deployable approach for a Hermes profile targeting kyverno is **ast-grep (via its official MCP server) for syntactic caller detection**, paired with **go-apidiff for public API break detection between branches**, with **gopls/mcp-language-server as an optional higher-fidelity layer for maintainers willing to run `go mod download` per worktree**. Each tool has a clear niche, clear limits, and a practical installation path.

## gopls delivers call-site intelligence but needs deps resolved

**gopls** (the official Go language server) is the highest-fidelity tool available for understanding semantic relationships in Go code. Via its LSP JSON-RPC protocol, it supports `textDocument/references` (every call site of a symbol across the whole workspace), `callHierarchy/incomingCalls` and `callHierarchy/outgoingCalls` (full bidirectional call graph), and `textDocument/implementation` (which concrete types implement a given interface). Two ready-made MCP servers wrap gopls: **mcp-gopls** (`github.com/hloiseaufcms/mcp-gopls`, exposing `find_references`, `go_to_definition`, `get_hover_info`, `check_diagnostics`, `analyze_coverage`) and **mcp-language-server** (`github.com/isaacphi/mcp-language-server`, exposing `definition`, `references`, `diagnostics`, `hover`, `rename_symbol`, `edit_file`). Both install with a single `go install` command and configure via workspace path + GOPATH env vars. The critical constraint is that **gopls uses `go/packages` with `NeedTypes`/`NeedTypesInfo`, which requires `go list` to succeed** — meaning the PR branch needs its dependencies resolved (`go mod download` or vendor/) but does NOT need `go build` to produce binaries. On a kyverno-scale repo with vendored deps, this is fast. On a PR branch without vendor/, you pay ~30–60s of `go mod download` per worktree. Neither MCP server currently exposes call hierarchy as a tool (only `find_references`), so the highest-value gopls feature for PR sequencing — "what calls the function being changed in PR A" — IS available, but `callHierarchy/incomingCalls` requires writing a thin custom MCP plugin or calling the LSP directly. `([gopls navigation features](https://go.dev/gopls/features/navigation))` `([mcp-gopls](https://playbooks.com/mcp/hloiseaufcms-gopls))` `([mcp-language-server](https://playbooks.com/mcp/isaacphi-language-server))`

## ast-grep gives fast syntactic caller detection with no build step

**ast-grep** is the practical no-build alternative that still provides meaningfully more than text search. It parses Go source code into ASTs and lets you match structural patterns — `find_code` and `find_code_by_rule` across a codebase — without invoking the Go toolchain at all. The **official ast-grep MCP server** (`github.com/ast-grep/ast-grep-mcp`) exposes four tools: `dump_syntax_tree`, `test_match_code_rule`, `find_code`, and `find_code_by_rule`. Installation requires the ast-grep binary (via `brew install ast-grep` or `cargo install ast-grep`) plus `uvx` for the Python MCP runner. The workflow for PR sequencing: extract the function/method names being added, removed, or renamed in a PR diff, then run `find_code` with a structural pattern like `changedMethod($$$)` across the main branch (or another PR's branch) to find all call sites. This won't resolve types — a pattern `Reconcile($$$)` will match ANY method named Reconcile, not just kyverno's specific one — but for a codebase where naming is reasonably unique (which kyverno's internal package names largely are), this catches the majority of meaningful cross-PR interactions. Critically, **this works on a raw git worktree without any module setup**, making it viable for scanning all 107 open PR branches efficiently. `([ast-grep MCP](https://github.com/ast-grep/ast-grep-mcp))` `([ast-grep overview](https://news.ycombinator.com/item?id=38590984))`

## go-apidiff catches the highest-risk ordering constraint: public API breaks

**go-apidiff** (`github.com/joelanford/go-apidiff`) is a CLI tool that compares exported Go API compatibility between two git commits. Run `go-apidiff main pr-branch-sha` and it outputs categorized breaking vs compatible changes — removed exports, changed method signatures, type incompatibilities. It uses `go/packages` with type parsing so it needs deps resolved, but no binary compilation. **relimpact** (from kitemetric.com) does the same thing with broader scope (API changes + doc changes + file changes by type) and accepts `--old`/`--new` git refs including branch names. Either tool answers the question: "does PR A remove or break a public symbol that any other PR might depend on?" For kyverno, where many PRs add new types to `api/*_types.go` and others add controllers that use those types, this is directly actionable: if go-apidiff shows a type removal or signature change between a PR and main, any other open PR touching files that import the affected package has a potential ordering constraint. This is the complement to the Hermes plugin's generated file ordering (which already handles `api/*_types.go → zz_generated.*`) by catching the inverse case: API breaks that the generated files don't reflect. `([go-apidiff](https://beta.pkg.go.dev/github.com/joelanford/go-apidiff@v0.4.0))` `([relimpact](https://kitemetric.com/blogs/introducing-relimpact-a-blazing-fast-release-impact-analyzer-for-go))`

## SCIP-go is the richest source of truth but needs a pipeline

**scip-go** (Sourcegraph's official Go SCIP indexer) produces an `index.scip` file containing every symbol definition and reference with type resolution — the closest thing to a ground-truth semantic index of a Go codebase. It correctly handles interface dispatch, type aliases, and cross-package calls in ways that tree-sitter and ast-grep cannot. However, it **requires a functioning Go build environment** (the Sourcegraph docs explicitly note it must run after Go environment setup), takes 30–90 seconds on a kyverno-scale codebase, and has no off-the-shelf MCP wrapper for PR comparison. Two community projects build on SCIP toward MCP: **synaptic-scip** (`github.com/IEatCodeDaily/synaptic-scip`) combines tree-sitter extraction with scip-go semantic enrichment and exposes 29 MCP tools including explicit PR review and impact analysis tools; **codegraph** (`github.com/techsavvyash/codegraph`) stores scip-go output in Neo4j and exposes 9 MCP tools for path finding, impact analysis, and Cypher queries. The base **synaptic/CodeGraph** tool (colinvaughn variant) skips SCIP and uses tree-sitter only, gives 29 MCP tools including callers, reverse dependencies, and change forecasting, and requires NO build step — making it the most immediately deployable graph-based tool. The tradeoff: tree-sitter analysis misses dynamic dispatch and interface polymorphism. For kyverno's reconciler-heavy codebase, where much of the important logic flows through `client.Get`/`client.Update` calls on specific types, this ambiguity matters. `([synaptic-scip](https://github.com/IEatCodeDaily/synaptic-scip))` `([codegraph SCIP+Neo4j](https://github.com/techsavvyash/codegraph))` `([scip-go indexing](https://sourcegraph.com/docs/code-navigation/how-to/index-a-go-repository))`

## The tools that don't help with cross-PR semantics

Several candidates turn out to be dead ends for this use case. **staticcheck** and **golangci-lint** are purely single-codebase tools — they report issues within a codebase but have no concept of comparing two branches or detecting cross-PR semantic interactions. **difftastic** makes individual diffs more readable (structural rather than line-by-line) but has no PR-to-PR comparison capability. **GitHub's API** is at its ceiling with file-level data — it provides no function-level call graph, no symbol references, and no semantic dependency information; the dependency graph API tracks only package-level go.mod dependencies. **semamerge** (MCP server for semantic merge conflict detection) is TypeScript-only and not applicable to Go. **go/callgraph** (the `cmd/callgraph` CLI from `golang.org/x/tools`) generates a full program call graph but requires a complete build environment, is expensive on large codebases (VTA analysis on kyverno would likely OOM or take many minutes), and produces a single monolithic graph with no built-in PR comparison mechanism. **The golang guru/oracle tool is effectively retired**, replaced by gopls. `([difftastic](https://github.com/Wilfred/difftastic))` `([go/callgraph](https://pkg.go.dev/golang.org/x/tools/go/callgraph))` `([semamerge](https://mcp.so/servers/semamerge))`

## Conclusion

The realistic bang-for-buck recommendation for a Hermes AI agent profile targeting kyverno is a **three-layer stack, incrementally adoptable**: (1) **ast-grep MCP** as the zero-setup baseline — install it once globally, run structural pattern searches across PR branches without any module setup, catch the majority of cross-PR call-site overlaps in seconds; (2) **go-apidiff or relimpact** as a per-PR gate — run it between main and each PR branch (requires `go mod download` once), output the breaking API changes, and flag any other open PR importing the affected packages as potentially dependent; (3) **mcp-language-server (gopls)** for deep interactive analysis when a maintainer wants to understand a specific conflict — configure it once per repo, use `find_references` for any symbol to get type-resolved caller locations across the workspace. The synaptic/CodeGraph tool is worth watching but is tree-sitter-only in its current no-build form, which limits precision for Go's interface-heavy code patterns. The scip-go + synaptic-scip pipeline offers the highest fidelity but requires a build step and custom integration work. None of the three recommended tools require changes to the kyverno repo itself, and all are installable by a maintainer in under 10 minutes alongside a Hermes profile.

