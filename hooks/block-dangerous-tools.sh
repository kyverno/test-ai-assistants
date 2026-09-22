#!/bin/bash
# pre_tool_call hook. Hermes pipes the event as JSON on stdin (never env
# vars) and only invokes this script when config.yaml's matcher already
# matched tool_name against merge|delete_repo|force_push — so every
# invocation here is already a match; there is no non-blocking branch.
# fail_closed: true on that same hook entry means a crash/timeout on one of
# these already-suspicious calls blocks it instead of Hermes' shell-hook
# default (fail open). Backstop only — see config.yaml's header comment for
# why the real gates are GITHUB_EXCLUDE_TOOLS and tools.include, not this.
set -euo pipefail

tool="$(jq -r '.tool_name // empty')"

jq -n --arg tool "$tool" \
  '{"action": "block", "message": ($tool + " is not permitted for kyverno-assistant — see SOUL.md")}'
