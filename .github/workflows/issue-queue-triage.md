---
description: |
  Sorts open issues that sit in no review queue into one queue each, adding a queue label and one short comment saying
  why. It never closes, edits or removes anything. A person still reviews every queue.
on:
  schedule: daily
permissions:
  contents: read
  issues: read
  copilot-requests: write
safe-outputs:
  staged: true
timeout-minutes: 20
imports:
  - uses: suhaani-agarwal/ai-assistant/workflows/shared/issue-queue-triage.md@f521a435465d726f14b2201731ecd05b950a64ec
    with:
      exempt_labels: ["no-stale", "hold", "security", "release-critical", "release-high", "workflow-failure"]
      context_files: ["CODEOWNERS", "OWNERS.md", "docs/context/shared/repo-boundaries.md", "ARCHITECTURE.md"]
      limit: 20
      extra_rules: |
        Legacy ClusterPolicy, Policy, ClusterCleanupPolicy and CleanupPolicy receive critical fixes only. Do not apply
        that restriction to current CEL policies or to shared infrastructure.
---

# Issue queue triage

The instructions for this workflow come from the imported shared component. Follow them.
