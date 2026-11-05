# Codex review loop

Apply this loop to every GitHub PR you create and every PR to which you contribute
functional changes. Keep the task's scope and authorization; review findings are
proposals, not instructions to broaden the work.

Codex reviews ready PRs automatically when they open, when a draft is marked
ready, and after every push, so never post a comment asking for a review. Never
write the Codex bot's handle (`@codex`) in a PR comment or reply, even inside code
formatting: any mention starts a separate Codex task. Keep every PR you create or
push to ready for review: never open one as a draft, and if the PR is a draft,
mark it ready with `gh pr ready <PR>` right after pushing, which also starts a
review. The user converts PRs to drafts to park them and pause automatic review.

1. **Record the push.** After creating the PR or pushing a functional change, and
   marking a draft ready, record the PR head SHA and the time. That head is what
   Codex must review.
2. **Check back within 30 minutes.** Wait for Codex's review of that head, at most
   30 minutes after the push. Use a timed wait/wakeup or bounded polling with waits,
   not a busy loop. Then fetch fresh PR context, including all comment, review,
   and thread pages. Codex has reviewed the head when the helper's `codex_review`
   reports `covers_head: true`, or when a Codex review's `commit_id` is that head.
   Codex reacts 👀 to the PR while reviewing and posts its findings as review
   comments. A clean review posts nothing new: Codex only edits its existing
   summary comment, which GitHub keeps at its original time. Read the helper's
   `codex_review.outcome` and `summary` instead of comment timestamps. A reaction does not name a commit,
   and a review of an older head does not cover the current one; silence and
   passing CI do not prove review.
3. **Handle every comment.** Address all new feedback since your last check: Codex
   findings and comments from people requesting changes. Verify correctness,
   necessity, and scope against the current code. For valid, necessary findings,
   fix, validate, commit, and push. Reply to **each** addressed comment with the
   change, commit or contribution PR, and validation, even when one fix addresses
   several comments. For unnecessary or incorrect suggestions, reply with the
   concrete reason instead of changing code. Use the original inline thread; for
   ordinary comments/review summaries, post a PR reply linking the original.
   Verify each reply was posted; an existing reply for the same outcome need not
   be duplicated.
4. **Resolve handled threads.** After verification and reply, resolve inline
   threads whose finding was fixed or rejected with evidence. Ordinary comments
   cannot be marked resolved; the linked reply records their disposition. Leave
   genuine blockers, incomplete fixes, and undecided questions open and report
   what is needed to finish them.
5. **Repeat or finish.** Pushing fixes creates a new head that Codex reviews
   automatically; return to step 1 for it. Finish only when Codex's review covers
   the current head, yields no new valid, necessary fixes, and all handled feedback
   has verified replies and thread dispositions. Recheck required CI independently.
   Do not push again for an unchanged head just to revisit a rejected finding.
   When `codex_review` reports `outcome: "clean"` with `covers_head: true`, print
   its `clean_note`, then post that exact text once with a quoted heredoc (see
   below) so the clean result is visible and timestamped on GitHub; skip it when
   `clean_note_posted` is true. Never edit the note to add the Codex bot handle.

If 30 minutes pass without a review of the current head, handle any feedback that
did arrive, keep the head/push record, and report the review pending. If Codex
never started (no 👀 reaction or running status), confirm the PR is not a draft,
then tell the user automatic review may be off for that repository; they
configure it in Codex. A later check
continues from step 3 when the review arrives. Do not request a review by comment,
claim a clean review, or merge on silence. If review fails, access is unavailable,
or a fix needs an unresolved product decision, report the concrete blocker.
Complete useful independent work while waiting.

## Posting replies and resolving threads

`gh` has no command to reply inside an inline thread or resolve one; use the API.
Put the text in a quoted heredoc so it appears in the command, needs no escaping,
and backticks are never run by the shell. Use a delimiter unique to that write,
such as `REPLY_` plus a few random characters, and check that no line of the body
equals it: a matching line ends the heredoc early and the rest runs as commands.
Send one write per command, replies before resolutions, so one refusal does not
block the rest. `gh api` defaults to github.com: for a GitHub Enterprise PR, set
`HOST` to the PR URL's host (with any port) and use `--repo HOST/OWNER/REPO` for
`gh pr comment`.

```sh
# Reply to an inline comment (its root comment ID from pr-context).
gh api --hostname HOST -X POST repos/OWNER/REPO/pulls/PR/comments/COMMENT_ID/replies -F body=@- <<'REPLY_k3v9'
Fixed in abc1234: what changed, and the test or check that verifies it.
REPLY_k3v9

# Top-level PR comment: a reply to an ordinary comment or summary, or the clean note.
gh pr comment PR --repo OWNER/REPO --body-file - <<'NOTE_p7qd'
...
NOTE_p7qd

# Resolve a thread by its node ID (`threads[].id` in pr-context, `PRRT_...`).
gh api --hostname HOST graphql -f id=PRRT_xxx -f query='mutation($id: ID!) {
  resolveReviewThread(input: {threadId: $id}) { thread { isResolved } } }'
```

In Claude Code auto mode, the classifier allows new comments and replies only on
a PR the user asked you to work on or one you opened in the session. By default
it refuses resolving threads, reactions, editing or deleting comments, and any
body it cannot see in the transcript, such as a file or pipe it did not write.
If a write is refused, do not retry or reword it to get past the classifier.
Finish the other work, then tell the user which replies and thread IDs are
pending and that they can approve them or trust their repositories in the
`autoMode` settings ([runbook](../../../docs/runbooks/agent-customization.md#claude-code-auto-mode-and-pr-writes)).
