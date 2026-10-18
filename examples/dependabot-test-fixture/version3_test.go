package main

import (
	"os"
	"strings"
	"testing"

	_ "github.com/google/subcommands"
)

// Same deterministic "stale test fixture" pattern as version_test.go / version2_test.go, for a fourth
// dependency, to get a clean PR uncontaminated by earlier test rounds' attempt-cap comment history.
const expectedSubcommandsVersion = "v1.2.0"

func TestSubcommandsVersionPin(t *testing.T) {
	data, err := os.ReadFile("go.mod")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(data), "github.com/google/subcommands "+expectedSubcommandsVersion) {
		t.Errorf("go.mod no longer pins subcommands at %s — update expectedSubcommandsVersion in this file to match the new version", expectedSubcommandsVersion)
	}
}
