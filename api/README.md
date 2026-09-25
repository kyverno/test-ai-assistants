# Test fixture

Mirrors `kyverno/kyverno`'s real `api/**` codegen-fanout path (see
`skills/kyverno-context/SKILL.md`) so test PRs touching this directory
exercise the generated-file-conflict detection for real, without needing
`kyverno/kyverno`'s actual codegen. No real generated code lives here.
