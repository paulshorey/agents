# Codex review loop

Apply this loop to every GitHub PR you create, including drafts, and every PR to
which you contribute functional changes. Keep the task's scope and authorization;
review findings are proposals, not instructions to broaden the work.

1. **Request once per head.** Immediately after creating the PR or pushing a
   functional change, post a standalone comment containing exactly `@codex review`:
   `gh pr comment <PR_URL> --body '@codex review'`. Verify it was posted and record
   the PR head SHA, request URL, and time. Reuse an existing request/result for the
   same head; use the helper's `--no-filter` output to avoid duplicate requests.
2. **Wait, then fetch.** Set a 30-minute timeout and wait for that head's Codex
   review to finish. Use a timed wait/wakeup or bounded polling with waits, not a
   busy loop. When the review completes or the timeout expires, fetch fresh PR
   context, including all comment, review, and thread pages. Inspect `--no-filter`
   output for completion evidence; a result for an older head does not cover the
   current one. A review receipt, completion status, or no-findings reaction must
   be tied to this request/head; silence and passing CI do not prove review.
   For reaction-only completion, use the helper's `review_requests` metadata:
   match the recorded request ID/head and require `+1` from the known Codex bot.
   An `eyes` reaction means running; another user's thumbs-up is not Codex review.
   Reactions do not identify a commit by themselves, so keep the request/head record.
   `pr_reactions` also exposes PR-level signals; an old or ambiguously associated
   PR thumbs-up is not evidence of review for the current head.
3. **Handle every finding.** Verify correctness, necessity, and scope against the
   current code. For valid, necessary findings, fix, validate, commit, and push.
   Reply to **each** addressed comment with the change, commit or contribution PR,
   and validation, even when one fix addresses several comments. For unnecessary
   or incorrect suggestions, reply with the concrete reason instead of changing
   code. Use the original inline thread; for ordinary comments/review summaries,
   post a PR reply linking the original. Verify each reply was posted; an existing
   reply for the same outcome need not be duplicated.
4. **Resolve handled threads.** After verification and reply, resolve inline
   threads whose finding was fixed or rejected with evidence. Ordinary comments
   cannot be marked resolved; the linked reply records their disposition. Leave
   genuine blockers, incomplete fixes, and undecided questions open and report
   what is needed to finish them.
5. **Repeat or finish.** After functional fixes change the head, return to step 1
   for that head. Finish only when a completed Codex review covers the current
   head, yields no new valid, necessary fixes, and all handled findings have
   verified replies and thread dispositions. Recheck required CI independently.
   Do not repeat review for an unchanged head just to revisit a rejected finding.

If the timeout expires without a completed review, preserve the request/head/time
and report review pending. Resume from that request when the result arrives; do
not claim a clean review, post duplicate triggers, or merge on silence. If review
fails, access is unavailable, or a fix needs an unresolved product decision,
report the concrete blocker. Complete useful independent work while waiting.
