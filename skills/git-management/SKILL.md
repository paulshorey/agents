---
name: git-management
description: Manage Git branches, publishing, and the full GitHub PR lifecycle, including review feedback, checks, conflicts, and authorized merges. Use whenever committing, pushing, creating a PR, contributing to an existing PR, or maintaining PRs.
---

# Git and pull requests

Follow the request, repository rules, protections, and holds. Routine commits,
pushes, PR updates, and review replies belong to the task handoff. Read-only work
needs no empty PR; publishing or completing review does not authorize a merge.

1. **Inspect.** Fetch refs; check repository, branch, worktree, upstream, unpushed
   commits, and existing PR. Preserve unrelated or ambiguously owned work and
   active processes. Use an isolated checkout if switching would disturb them.
2. **Choose a branch.** Continue a feature branch only for the same ongoing task.
   Start independent work from updated `main` or a verified base; never reuse a
   merged branch. Use an unmerged base only when required. Move task edits off
   `main` before committing; do not publish pre-existing work to clear a checkout.
3. **Publish.** Work in your own worktree, not a checkout the user is also using,
   and confirm `git branch --show-current` is the intended branch right before each
   commit (the user may switch a shared checkout). Run relevant checks, stage only
   task files, commit, push, and create or update the task PR. Always open PRs ready for review, never as drafts (no
   `--draft`), even for unfinished or blocked work; state what remains in the
   body. After pushing to a draft PR, mark it ready with `gh pr ready <PR>`.
   Drafts are for PRs the user parks to pause automatic review. Keep the PR
   title/body aligned with the final problem, behavior, material decisions,
   validation, and remaining work; scale detail to complexity.
4. **Complete the review loop.** For every GitHub PR you create or contribute code
   to, follow the [Codex review loop](references/review-loop.md). Codex reviews
   ready PRs automatically after every push; never comment to request review.
   Check back within 30 minutes of each functional push, fetch all latest
   feedback, address each comment, and repeat after fixes until the current head
   has no new valid issues to fix. A timeout or missing review is pending review,
   never a clean result. Keep the PR's `agent/ready` status current with
   `scripts/pr-ready.py` (working, blocked, ready) so the developer can see when it
   is safe to merge.
5. **Maintain or merge.** For reviews, conflicts, failed checks, or authorized
   merges, read [PR maintenance](references/pr-maintenance.md). Review the exact
   current head; verify bot suggestions rather than accepting them automatically.
6. **Finish cleanly.** Confirm task commits are pushed, addressed comments have
   verified replies, and the PR reflects the final state. Return temporary review
   checkouts to `main` when requested; preserve active feature checkouts. Report
   the PR, checks, review outcome or timeout, final branch, and unpublished work or
   synchronization blockers. Never discard changes or force-push to switch tasks.

## PR context

```sh
python3 ~/.agents/skills/git-management/scripts/pr-context.py <PR_URL> --output <TEMP_FILE>
```

The JSON can exceed tool-output limits; write it to a temporary file and query it
(for example with `jq`) rather than reading truncated terminal output. Add `--diff`
for code changes and `--hunks` for inline-comment diff context. `codex_review`
reports which commit Codex last reviewed and whether that covers the current head
(`covers_head`). The default output drops Codex's summary comment and bare
review-request comments and strips About-Codex boilerplate from Codex comments;
human comments and Codex findings are never dropped. Use `--no-filter` to see
every comment unchanged. The helper fetches
all feedback pages and preserves reply IDs, review decisions, and thread state.
Never assume the first 30 comments are complete. See the
[helper guide](../../docs/runbooks/utilities.md#pr-context) for output and failures.

## Production promotions

For repositories using `main` for development and `prod` for production, read
[production promotions](references/production-promotions.md). Otherwise follow
the project's release workflow. A review loop does not override release holds or
authorize deployments, migrations, or a narrower release.
