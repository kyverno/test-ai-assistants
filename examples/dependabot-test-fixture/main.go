// dependabot-test-fixture exists only to give Dependabot's gomod ecosystem
// something real to bump, so copilot-dependabot-autofix.yml has actual PRs
// to react to. See examples/dependabot-test-fixture/README.md.
package main

import (
	"fmt"

	"github.com/google/uuid"
)

func main() {
	fmt.Println(uuid.New().String())
}
