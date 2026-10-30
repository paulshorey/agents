---
name: git-management
description: Manage task branches, commits, pushes, and PR handoffs while preserving existing work. Use when starting, continuing, or finishing changes in a Git repository.
---

# Git task management

Follow the current request and repository rules. Routine task commits, pushes,
and PR creation/updates are part of the handoff; read-only work needs no empty PR.

1. **Inspect.** Check repository identity, branch, worktree, upstream, unpushed
   commits, and existing PR; fetch current refs. Preserve unrelated or ambiguously
   owned work. Use an isolated checkout if switching would disturb it or a process.
2. **Choose the branch.** Continue an existing feature branch only for the same
   ongoing task. Start independent work from updated `main` or a verified base;
   never reuse a merged branch. Base work on an unmerged branch only when required
   by the task. Move task edits off `main` before committing. Do not publish
   pre-existing work merely to clear the checkout.
3. **Validate and publish.** Run relevant checks, stage only task files, commit,
   and push. Create a PR after the first push or update the existing task PR.
   Use a draft for unfinished or blocked work. Keep its title/body aligned with
   final scope: problem, resulting behavior, material decisions, validation, and
   remaining work. Scale detail to complexity; do not repeat every file or commit.
4. **Request review.** Immediately after creating a PR, including drafts, post
   a standalone comment containing exactly `@codex review` and confirm success.
   Request again after significant subsequent changes; avoid duplicate requests
   for an unchanged head. With GitHub CLI:
   `gh pr comment <PR_URL> --body '@codex review'`.
5. **Handle feedback.** Use [PR management](../pr-management/SKILL.md) for review,
   fixes, conflicts, and merges within the authorized scope. Report actionable
   concerns in a PR comment unless contributing the fix immediately.
6. **Finish cleanly.** Ensure task commits are pushed and the PR reflects the
   final state. Return a temporary review checkout to `main` when requested;
   preserve active feature checkouts. Report the PR, validation, final branch,
   and any unpublished work or synchronization blocker. Never discard changes
   or force-push just to switch tasks.

## Production promotions

When authorized, promote all current `main` to `prod` through a PR with head `main`,
base `prod`. Feature/conflict fixes land in `main` first. Preserve intentional
production differences and inspect production-only commits; narrow releases need
an explicit request. Follow the project's migration/release workflow, inspect
pending migrations even when code is synchronized, and verify the deployed commit,
application/database health, and retained data. An unmerged feature PR is not part
of the release. Report an already-current promotion only after relevant validation.
