# Trusted publish guard qualification

Source hardening landed on protected `main` at
`984fec7f7b00237460e9eb37a7d2bf5b526c9b13`. The source tree is
`6f6714a84af9387f727ff6ed8c6b697705f5cf85`.

The `publish-guard-trusted` workflow uses protected-base code to compare
candidate enforcement files, render policy, prior immutable objects, and
dependency-shadow names. Its status becomes a required protection only after
one exact-head pull request run proves the job is emitted by GitHub Actions,
passes, and is tied to the candidate SHA.

The active branch ruleset must then require `publish-guard-trusted` alongside
`publish-guard-check` and `validate`, with the same GitHub Actions app binding
and strict checks. Preserve code-owner review, last-push approval, and no
bypass actors. Read back the installed ruleset and a protected
default check after the transition.

This qualification is a repository control change. It does not render a new
subject, issue signer approval, publish to the operator stage, run the external
merge-queue fixture, rescan Daybreak, or change finding status. The historical
subject remains held at `stale_view` until a separately reviewed render
successor and publication authority exist.
