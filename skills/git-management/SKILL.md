---
name: git-management
description: Manage task branches, commits, pushes, and PR handoffs while preserving existing work. Use when starting, continuing, or finishing changes in a Git repository.
---

# Git task management

Follow the request and repository rules. Routine commits, pushes, and PR updates
are part of the handoff; read-only work needs no empty PR.

1. **Inspect.** Fetch refs; check repository, branch, worktree, upstream, unpushed
   commits, and existing PR. Preserve unrelated or ambiguously owned work. Use an
   isolated checkout if switching would disturb edits or an active process.
2. **Choose a branch.** Continue a feature branch only for the same ongoing task.
   Start independent work from updated `main` or a verified base; never reuse a
   merged branch. Use an unmerged base only when the task requires it. Move task
   edits off `main` before committing; do not publish pre-existing work to clear
   the checkout.
3. **Publish.** Run relevant checks, stage only task files, commit, push, and create
   or update the task PR. Use a draft for unfinished or blocked work. Describe the
   problem, resulting behavior, material decisions, validation, and remaining work.
   Keep the title/body aligned with final scope and scale detail to complexity.
4. **Request review.** Immediately after creating any PR, including drafts, post
   a standalone `@codex review` comment and verify it succeeded. Request again
   after significant changes; avoid duplicates for an unchanged head:
   `gh pr comment <PR_URL> --body '@codex review'`.
5. **Handle feedback.** Fetch the complete PR context with
   `python3 ~/.agents/skills/git-management/scripts/pr-context.py <PR_URL>`.
   Add `--diff` for code changes; see the [helper guide](../../docs/runbooks/utilities.md#pr-context).
   It paginates comments, reviews, and threads; never assume the first 30 comments
   are the complete history. Use [PR management](../pr-management/SKILL.md) for
   review, fixes, conflicts, and authorized merges. After validating and pushing
   a fix or improvement, **reply to every comment it addresses**, stating the
   change, commit, and validation. Reply in the original inline thread; for other
   comments, link the original in a PR reply. Verify each reply was posted;
   a commit, thread resolution, or final chat message does not replace it.
   Report actionable concerns in a PR comment unless fixing them immediately.
6. **Finish cleanly.** Confirm task commits are pushed, addressed comments have
   replies, and the PR reflects the final state. Return temporary review checkouts
   to `main` when requested; preserve active feature checkouts. Report the PR,
   validation, final branch, and unpublished work or synchronization blockers.
   Never discard changes or force-push just to switch tasks.

## Production promotions

For repositories using `main` for development and `prod` for production, an
authorized promotion merges all current `main` into `prod` through a PR with head
`main`, base `prod`. Feature/conflict fixes land in `main` first. Preserve intentional
production differences and inspect production-only commits; narrow releases need
an explicit request. Follow the project's migration/release workflow, inspect
pending migrations even when code is synchronized, and verify the deployed commit,
application/database health, and retained data. An unmerged feature PR is not part
of the release. Report an already-current promotion only after relevant validation.
For other branch models, follow the project's release workflow.
