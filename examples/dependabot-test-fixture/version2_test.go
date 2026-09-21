package main

import (
	"os"
	"strings"
	"testing"
)

// Same deterministic "stale test fixture" pattern as version_test.go, for a second dependency so we can test
// the autofix pipeline fresh without prior comment history throwing off the attempt caps.
const expectedPkgErrorsVersion = "v0.8.0"

func TestPkgErrorsVersionPin(t *testing.T) {
	data, err := os.ReadFile("go.mod")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(data), "github.com/pkg/errors "+expectedPkgErrorsVersion) {
		t.Errorf("go.mod no longer pins pkg/errors at %s — update expectedPkgErrorsVersion in this file to match the new version", expectedPkgErrorsVersion)
	}
}
