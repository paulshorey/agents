---
name: git-management
description: When starting, continuing, or finishing changes in a Git repository, and whenever committing or pushing task work - keep each new task on a separate feature branch. Open or edit a PR as the engineering handoff for each task.
---

# Git task management

Manage the branch and PR throughout the task. Routine commits, pushes, and PR creation or updates are authorized; respect current instructions and repository rules. Read-only work needs no new branch or empty PR.

1. **Inspect before working.** Check the current branch, working tree, unpushed commits, upstream, and existing PR. Fetch current remote state. Understand what previous changes accomplish before deciding whether the new request continues that task.
2. **Publish previous work.** Before new work, commit changes that clearly belong to the current feature branch and push unpushed commits. Stage only relevant files. Ensure that branch has an open PR before leaving it; use a draft for unfinished work. Put changes found on `main` on an appropriate feature branch before committing. Preserve unrelated or ambiguously owned work; use another worktree or clarify ownership.
3. **Choose the task branch.** Reuse a feature branch only to continue the same ongoing task; similar files alone are insufficient. For an independent task, or when on `main`, create a new feature branch from updated `main` or the verified base. Do not reuse a merged task's branch. Start from unmerged work only when the task explicitly depends on it.
4. **Keep the PR current.** Validate, commit, and push task changes. After every push, create a PR if none is open; otherwise update it. At completion, ensure intended changes are committed and pushed and the PR reflects the final scope. Revise its title and description as scope evolves; a continuing task keeps its PR.

Write PR descriptions as durable handoffs to future engineers and AI agents. Lead with the problem and resulting behavior. Include relevant scope, product/design decisions and rationale, architecture and technical choices, constraints and tradeoffs, integration details, validation commands and results, and remaining work or risks. Explain context that the changed code cannot convey. Scale detail to complexity, preserve useful earlier decisions, and remove stale statements rather than narrating commits or repeating the diff.

Preserve local work and busy checkouts; never discard changes or force-push merely to switch tasks. If publishing or switching is blocked, report the specific blocker and next step. End with the branch, PR link, validation outcome, and any remaining unpublished work.
