- write actions cannot happen unless your PAT is generated specifically for kyverno with you as a kyverno member
- make a slack bot app in kubernetes slack workspace and request them to give permission to install it. 
- change the slack channel cred to the kyverno-dev maintainers channel
- security vulnerability scanning issue and pr raising - updating the review bots accordingly
- memory , user specific stuff
- github dicussions
- cron jobs that suggest proper pr queues


 Three real options, not a made-up list:

  1. Personal instance per maintainer (today's design) — each maintainer installs their own, own token, own machine, own Slack
     app if they want Slack.
  2. Shared bot, read-only — one always-on bot the whole team can @mention for merge-sequence/review-briefs/questions, but
     acting (label/approve/comment) still requires a maintainer's own personal CLI instance. No attribution problem, since
     nothing gets posted anywhere.
  3. Shared bot, full capability — same bot also takes actions, but every action is attributed to one dedicated service
     account (a real kyverno-bot GitHub account with its own limited token), not any individual maintainer's identity. This is
     a deliberate governance decision the maintainers would need to actually make, not something to default into.
