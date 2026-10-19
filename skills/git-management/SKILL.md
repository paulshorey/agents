---
name: git-management
description: When starting, continuing, or finishing changes in a Git repository, and whenever committing or pushing task work - keep each new task on a separate feature branch. Push changes. Open or edit a PR as the engineering handoff for each task.
---

# Git task management

**Manage the branch and PR throughout the task.** Routine commits, pushes, and PR creation or updates are authorized. Respect current instructions and repository rules. Read-only work needs no new branch or empty PR.

**Inspect before working.** Check the current branch, working tree, unpushed commits, upstream, and existing PR. Fetch current remote state. Understand what previous changes accomplish before deciding whether the new request continues that task.

**Publish previous work.** Before new work, commit changes that clearly belong to the current feature branch and push unpushed commits. Stage only relevant files. Ensure that branch has an open PR before leaving it; use a draft for unfinished work. Put changes found on `main` on an appropriate feature branch before committing. Preserve unrelated or ambiguously owned work; use another worktree or clarify ownership.

**Choose the task branch.** Reuse a feature branch only to continue the same ongoing task; similar files alone are insufficient. For independent implementation work, or when implementing on `main`, create a new feature branch from updated `main` or the verified base. Do not reuse a merged task's branch. Start from unmerged work only when the task explicitly depends on it. Production promotions use the existing branches as described below.

**Promote the full development branch.** For repositories using `main` for development and `prod` for production, an authorized promotion merges all of current `main` into `prod`: use a PR with head `main`, base `prod`. Feature work and conflict fixes land in `main` first. Inspect production-only fixes and preserve intentional environment differences. Use a narrower release only when explicitly requested. Promotion includes necessary production database migrations through the project's workflow, affected checks, and verification of the deployed commit and application/database health. Check pending migrations even when code is already synchronized; report an up-to-date promotion once validation passes. Distinguish unmerged PRs from work ready for promotion.

**Keep the PR current.** Validate, commit, and push task changes. After every push, create a PR if none is open; otherwise update it. Immediately after creating any PR, including drafts, post a standalone comment containing exactly `@codex review` using `gh pr comment <PR_URL> --body '@codex review'`, and confirm it was posted before proceeding. At completion, ensure intended changes are committed and pushed and the PR reflects the final scope. Revise its title and description as scope evolves; a continuing task keeps its PR.

**Resolve PR comments.** PRs are automatically reviewed by Cursor bot. Cursor will suggest fixes in another branch and PR. Review that suggestion PR. If you agree with the fix, go ahead merge it. If you disagree with the fix, close that PR. Either way, reply to the review comment with your assessment and action. Be careful - some reviews will be false positives or out of scope, so do not assume just because Cursor bot made a comment and opened a suggestion fix PR that it's worth merging. If there is no suggestion PR but only a comment, then think about what it says and how it should be addressed. Go ahead and make the fix or improvement if necessary, or not if unnecessary. Either way, reply to the comment and resolve it.

**Write PR descriptions as durable handoffs** to future engineers and AI agents. Lead with the problem and resulting behavior. Include relevant scope, product/design decisions and rationale, architecture and technical choices, constraints and tradeoffs, integration details, validation commands and results, and remaining work or risks. Explain context that the changed code cannot convey. Scale detail to complexity, preserve useful earlier decisions, and remove stale statements rather than narrating commits or repeating the diff.

**Preserve local work and busy checkouts.** Never discard changes or force-push merely to switch tasks. If publishing or switching is blocked, report the specific blocker and next step. End with the branch, PR link, validation outcome, and any remaining unpublished work.

---

**Self-reflection and improvement:**
Consider these instructions with your current use case. Can anything be done do to make your job easier? Can we improve these instructions to help make the task easier next time? Edit this skill `skills/git-management` with any improvements you can think of for next time or suggest possible improvements.
