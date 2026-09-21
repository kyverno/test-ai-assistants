package main

import (
	"testing"

	"github.com/google/go-cmp/cmp"
)

func TestGreeting(t *testing.T) {
	got := Greeting("world")
	want := "hello, world"
	if diff := cmp.Diff(want, got); diff != "" {
		t.Errorf("Greeting mismatch (-want +got):\n%s", diff)
	}
}
