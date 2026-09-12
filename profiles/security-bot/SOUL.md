# security-bot — not yet implemented (build plan Phase 4)

Will fire on `issues.labeled` where `label.name == "security"`. Unlike
every other bot here, this profile must NEVER be given a `gh issue comment`
/ `add_issue_comment` tool — its toolset should only ever include a Slack
delivery tool, posting to a private maintainers-only channel. That
restriction is enforced the same way every other tool restriction in
kyctrl is enforced: by what's listed under this profile's toolset in
`config.yaml`, not by an instruction in this file.

See `docs/adding-a-new-bot.md` and the build plan for this bot's full spec.
