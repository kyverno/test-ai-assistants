# kyverno-sequencer

A bundled Hermes plugin, not a skill. Registers one tool, `sequence_prs`, that `pr-queue` calls
with already-fetched PR metadata and gets back a deterministic candidate merge order: file-risk
classification, a hard-precedence graph (stacked branches, generated-file input/output
mechanically; interface/dependency-usage edges supplied as `precedence_hints`), cycle detection,
and a weighted rank solve (milestone urgency, age, size, e2e-gate risk, review-readiness) via
CP-SAT, falling back to a stdlib greedy heuristic if `ortools` isn't installed.

Ships automatically on `hermes profile install .` (see `docs/architecture.md`). No GitHub/Slack
access of its own — a pure function over its input, called once per queue-build. Its output is a
**candidate**, not a verdict: `pr-queue` still checks it against Dependabot diagnosis and Slack
context before presenting a final recommendation.

`scripts/install.sh` installs `ortools` automatically; the greedy fallback covers anyone who
skips that script.
