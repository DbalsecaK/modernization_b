package main

import "testing"

// TestSeed compiles a test binary while the image is built, so the build cache holds the testing packages too.
func TestSeed(t *testing.T) {
	t.Parallel()
}
