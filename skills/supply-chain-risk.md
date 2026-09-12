# Supply chain risk (Socket.dev)

Context for why `kyctrl_verdict` may FLAG on an otherwise-clean update.

The policy engine calls Socket.dev's API for each dependency touched by
the PR (parsed from the commit metadata, not the diff) and takes the
lowest score returned. If that score is below
`settings.yaml`'s `dependabot_bot.socket_score_threshold`, the verdict is
FLAG even if CI is green and the ecosystem/update-type are otherwise fine.

If you're writing the comment for a Socket.dev-triggered FLAG, name the
actual package and score from `kyctrl_verdict.reasons` — "the `foo`
package scored 41/100 on Socket.dev (below our 70 threshold)" is useful;
"a dependency looked risky" is not.

If Socket.dev's API is unreachable or a package isn't found in Socket.dev's
index, the engine treats that as a FLAG (fail closed, not fail open) — say
so plainly rather than implying the score was checked and passed.
