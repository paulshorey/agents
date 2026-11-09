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

The developer can't see when you are working, so every PR you create or push to
carries an `agent/ready` status on its head (see [Readiness status](#readiness-status)).
It is pending while you work or wait for review, fails when you need the
developer, and passes only when `pr-ready.py ready` has verified the PR.

1. **Record the push.** After creating the PR or pushing a functional change, and
   marking a draft ready, record the PR head SHA and the time. That head is what
   Codex must review. Mark it `working` ("waiting for Codex review of SHA").
2. **Check back within 30 minutes.** Wait for Codex's review of that head, at most
   30 minutes after the push. Use a timed wait/wakeup or bounded polling with waits,
   not a busy loop. Then fetch fresh PR context, including all comment, review,
   and thread pages. Codex has reviewed the head when the helper's `codex_review`
   reports `covers_head: true`, or when a Codex review's `commit_id` is that head.
   Codex reacts 👀 to the PR while reviewing and posts its findings as review
   comments. A clean review posts nothing new: Codex only edits its existing
   summary comment, which GitHub keeps at its original time. Read the helper's
   `codex_review.outcome` and `summary` instead of comment timestamps. If the
   outcome is `ambiguous`, read the earlier Codex review of that commit and handle
   its findings; never treat it as clean. A reaction does not name a commit,
   and a review of an older head does not cover the current one; silence and
   passing CI do not prove review.
3. **Handle every comment.** As soon as you have new feedback to handle, mark the
   head `working` with what you are fixing, before any edit. Address all new
   feedback since your last check: Codex findings and comments from people
   requesting changes. Verify correctness,
   necessity, and scope against the current code. For valid, necessary findings,
   fix, validate, commit, and push. The user may merge or close the PR while you
   work, so check its state (`pr.state`, `pr.merged`) just before pushing, and
   after pushing confirm that `pr.head.sha` is the pushed commit and the PR is
   still open. If it was merged, put the fixes on a new branch from the updated
   base, open a new PR, and link it in the replies. If it was closed without
   merging, keep the fixes on the branch and ask the user before opening a
   replacement PR. Reply to **each** addressed comment with the change, commit or
   contribution PR, and validation, even when one fix addresses several comments.
   For unnecessary or incorrect suggestions, reply with the concrete reason instead
   of changing code. Use the original inline thread; for ordinary comments/review
   summaries, post a PR reply linking the original. Verify each reply was posted;
   an existing reply for the same outcome need not be duplicated.
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
   Then run `pr-ready.py ready` with a note on validation (for example
   `--note "182 tests pass"`); it marks the head ready to merge only after its own
   check, and otherwise marks it pending with the unmet condition. Report to the
   user that the PR is ready to merge only after it succeeds.

If 30 minutes pass without a review of the current head, handle any feedback that
did arrive, keep the head/push record, and report the review pending. If Codex
never started (no 👀 reaction or running status), confirm the PR is not a draft,
then tell the user automatic review may be off for that repository; they
configure it in Codex. A later check
continues from step 3 when the review arrives. Do not request a review by comment,
claim a clean review, or merge on silence. If review fails, access is unavailable,
or a fix needs an unresolved product decision, report the concrete blocker.
Complete useful independent work while waiting. When you stop with work left or a
decision needed, mark the head `blocked` with what the developer must do; never
leave it `working` when nothing is running.

## Plan and documentation PRs

A PR that changes only plans or documentation gets at most three review rounds.
After the third, stop pushing, list the remaining findings for the developer to
decide, and mark the head `blocked`. Each round costs a push and rarely changes
the decision, so correct factual errors and leave wording preferences to the
developer.

## Check-back prompts

A timed check-back starts without this session's reasoning. Write its prompt as
facts: the PR, head SHA, push time, and exact observations, plus the assumption to
re-test. Never pass a conclusion forward as settled, such as "the token is
rejected"; write what was observed and "re-test this assumption" instead.

## Readiness status

```sh
python3 ~/.agents/skills/git-management/scripts/pr-ready.py working PR "fixing 4 Codex findings"
python3 ~/.agents/skills/git-management/scripts/pr-ready.py blocked PR "choose keep or drop the cache"
python3 ~/.agents/skills/git-management/scripts/pr-ready.py ready PR --note "182 tests pass"
python3 ~/.agents/skills/git-management/scripts/pr-ready.py status PR
```

`agent/ready` appears in the PR's checks. Where branch protection requires it, as
on `paulshorey/agents` `main`, GitHub disables merging until it passes, so a PR
cannot be merged while you are still fixing it. A new push leaves the new head
without the status, which reads as not ready until you verify again. `ready`
requires an open, non-draft, conflict-free PR, a clean Codex review of the head,
no unresolved threads or requested changes, and passing quality checks and statuses, and
it rereads checks and statuses just before posting. Never set success by any other
means. If it exits 3, you cannot create statuses on that repository (for example a
fork PR without push access upstream): post the readiness result as a PR comment
instead and tell the user. The status belongs to the head commit only; on
repositories that don't require branches to be up to date, a later base change
does not reset it.

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

The readiness helper treats the GitHub Actions completion observer and its
`PR checks finished` status as derived signals. For those repositories, it checks
the underlying head and test-merge checks, statuses, and queued workflows directly
to avoid waiting for a completion observer that is itself waiting for agent readiness.
