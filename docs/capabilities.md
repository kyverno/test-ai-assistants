# What kyverno-assistant can actually do right now

Written after the first live, working `kyverno chat` session against the
real `kyverno/test-ai-assistants` repo. Everything below reflects what the
three shipped skills (`kyverno-context`, `pr-queue`, `pr-actions`) and the
32-tool allowlist (`config.yaml`) actually enable — not the aspirational
design. See `docs/architecture.md` for why it's built this way.

## 1. Understanding the repo — `kyverno-context`

- Looks up the repo's **actual current labels** before ever filtering or
  applying one — never assumes a label like "ready-for-review" exists.
- Resolves **CODEOWNERS live**, including expanding `@org/team` entries to
  check whether the maintainer is actually a member — not just parsing the
  file text.
- Knows two fixed, pre-researched facts about `kyverno/kyverno`'s build:
  which paths (`api/**`) fan out to generated files, and which test suites
  only run post-merge (never on a PR) — this is what lets the queue reason
  about risk a green checkmark won't show.
- Can find and read any doc in the repo on demand (`AGENTS.md`,
  `CONTRIBUTING.md`, anything under `docs/`) via repo-wide code search,
  scoped to whatever the current question needs — not preloaded.

## 2. Building and explaining the review queue — `pr-queue`

Ask **"what's my review queue"** and it will:

- Fetch every open PR where you're a requested reviewer (including via
  team, not just direct requests).
- Filter to ready-for-review using the repo's real labels.
- Flag, explicitly and by name:
  - **Stacked PRs** — one PR's base branch is another queued PR's head.
  - **Generated-file conflicts** — two PRs both touch codegen inputs, so
    they'll conflict on generated files even if their own diffs don't.
  - **Package overlap** — same package touched without a git conflict, but
    still elevated review risk.
  - **Post-merge CI risk** — which PRs touch code paths only the
    post-merge-only suites would catch a problem in.
- Give every PR a one-line, citable reason for its position — not a bare
  sorted list.

Ask about **a specific PR** and it will:

- Explain it (diff, reviews, CI status, comments).
- Read and synthesize existing Copilot/CodeRabbit review output — and say
  plainly if neither has reviewed it yet, rather than implying a clean
  check happened. Can request a Copilot review if one's missing.
- Check whether the PR closes an issue, and whether another PR is also
  configured to close the same one (duplicate-effort signal).

Ask **"is anything else related to this"** and it searches issues/PRs for
mentions that aren't formally linked, citing what it actually found.

Tell it **"CI broke on main"** and it will look up the real failing run and
cross-reference it against the current queue by file overlap — it doesn't
poll or watch for this on its own; it only reasons about it when told.

Ask it to **post the queue to the maintainers' Slack channel** and it can,
separately from replying to you directly.

## 3. Taking action — `pr-actions`

Once you decide what to do, it can, using your own GitHub credentials:

- **Label** a PR — only with labels that actually exist on the repo.
- **Comment**, or edit an existing comment instead of duplicating one.
- **Review**: approve, request changes, or comment — including
  line-specific feedback and replying to an existing review thread (e.g.
  answering a Copilot comment).
- **Catch a branch up with its base** when you say "rebase this" — it will
  do this, but tells you honestly that it's a merge-update, not a real
  rebase (GitHub's API doesn't offer a true rebase), and warns you up front
  if the PR touches codegen inputs, since updating the branch won't
  regenerate stale generated files.

It will **not**:

- **Merge, ever.** No merge tool exists anywhere in its toolset. This isn't
  a rule it follows — the capability doesn't exist to invoke, enforced in
  three independent layers (server-side exclusion, Hermes-side allowlist, a
  hook backstop), each verified against the real running services, not
  assumed from documentation.
- Do a **true git rebase** (rewrite commit history) — no tool for it exists
  on purpose; that would need local git plus a force-push, which is
  deliberately excluded.
- **Watch for or auto-detect** anything — no webhook, no polling. It only
  acts when asked.

## How it actually works, briefly

- A single maintainer installs it as a **Hermes profile** and talks to it
  on the CLI or Slack — there's no server, no webhook receiver, nothing
  running when nobody's asking it anything.
- It uses **your own GitHub token**, scoped read + limited write (no merge,
  no admin, no Contents-write) — every action it takes is attributable to
  you, not an anonymous bot.
- It **never hardcodes** repo conventions (labels, CODEOWNERS, docs) —
  every skill re-resolves them live, every session, because they drift and
  because the same profile may later point at a different repo.
- It's built to **look things up rather than guess** on open-ended
  questions, not to follow a fixed script per anticipated question — see
  "Maintainer questions are open-ended" in `docs/architecture.md`.

## Honest current limits

- **One repo, one maintainer, per installed instance.** Not a fleet, not
  multi-tenant.
- **No blast-radius / call-graph analysis** — it approximates "what would
  this break" with text search (`search_code`), which is weaker than a
  real code-graph tool but needs no extra infrastructure. See
  `docs/architecture.md` for why that tradeoff was made deliberately.
- **Slack integration is two separate pieces** (the chat interface and the
  channel-reading/posting tool) — see `docs/architecture.md` if one works
  and the other doesn't.
- **Not validated against real maintainer workflows yet** — this is one
  person's first live session, not the 2-3-maintainer validation pass
  `docs/deployment.md` calls for before anything past v1.
