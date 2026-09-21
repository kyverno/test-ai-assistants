package main

import (
	"os"
	"strings"
	"testing"
)

// Mirrors a real pattern seen on kyverno/kyverno's own Dependabot PRs (e.g. #17570's Test_x509Decode failing
// after a sigstore bump changed real behavior): a test whose hardcoded expectation goes stale specifically
// because of the dependency bump this PR makes. This one is deterministic by construction — it reads go.mod
// directly — rather than relying on an upstream library's behavior actually differing between versions, which
// well-maintained libraries rarely do across a minor/patch bump.
const expectedGoCmpVersion = "v0.5.9"

func TestGoCmpVersionPin(t *testing.T) {
	data, err := os.ReadFile("go.mod")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(data), "github.com/google/go-cmp "+expectedGoCmpVersion) {
		t.Errorf("go.mod no longer pins go-cmp at %s — update expectedGoCmpVersion in this file to match the new version", expectedGoCmpVersion)
	}
}
