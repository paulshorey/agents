---
name: pr-management
description: Help manage opened PRs. When you notice a PR or feature branch needs attention, even without an explicit review request, go ahead review it, comment on it, address comments, merge main. Sync local git filesystem.
---

# Project maintenance

**Own the codebase you're working on.** Do not simply write code for the task at hand, but manage the entire project. Maintain any active PRs and feature branches. Review, fix, address feedback, merge ready work, and synchronize the user's local checkout. Routine fixes, pushes, PR comments, and ready merges are authorized; respect current instructions and repository rules.

**Synchronize.** Verify the repository, branches, PR state, and local work; fetch current remote state. If the local branch is behind its upstream, pull with `--ff-only`. Inspect divergence rather than resetting or force-pushing.

**Request Codex review immediately.** Immediately after creating any PR, including drafts, post a standalone comment whose entire body is `@codex review` before doing any other work. With GitHub CLI, run `gh pr comment <PR_URL> --body '@codex review'`. Confirm the comment was posted; if posting fails, report the review request as incomplete.

**Review.** If no review covers the current changes, review them. Fix obvious issues and improvements you are confident about; validate, commit, and push. If a fix needs product/design input or cannot be implemented conveniently, comment with findings and recommendations.

**Address feedback.** Evaluate unaddressed reviews and comments against current code. Fix valid concerns, validate, commit, push, and reply with the outcome. Resolve verified fixes. Explain and resolve false positives or justified findings outside scope; leave genuine blockers and undecided questions open. Avoid duplicate comments.

**Resolve feature-PR conflicts.** If conflicts block a feature PR, merge the latest fetched `main` into its feature branch, resolve conflicts, validate, commit, and push. Document decisions you cannot safely make; do not leave an unfinished merge blocking other work.

**Resolve PR comments.** PRs are automatically reviewed by Cursor bot. Cursor will suggest fixes in another branch and PR. Review that suggestion PR. If you agree with the fix, go ahead merge it. If you disagree with the fix, close that PR. Either way, reply to the review comment with your assessment and action. Be careful - some reviews will be false positives or out of scope, so do not assume just because Cursor bot made a comment and opened a suggestion fix PR that it's worth merging. If there is no suggestion PR but only a comment, then think about what it says and how it should be addressed. Go ahead and make the fix or improvement if necessary, or not if unnecessary. Either way, reply to the comment and resolve it.

**Repair checks.** Inspect failed build/check logs and fix understood causes. If blocked, comment with evidence and the developer's next step.

**Promote production.** Follow [Git management's full-release workflow](../git-management/SKILL.md): promotion PRs merge `main` into `prod`, including required database migrations and release validation. Ordinary feature PRs land in `main` first.

**Merge and update locally.** Merge when the current changes are reviewed, required checks and approvals are satisfied, and no conflicts or substantive blockers remain. Recheck the head before merging, respect branch protections, and verify the PR actually merged. Then update the primary checkout, not just a temporary review worktree:

- On `main`: pull the latest changes.
- On the merged PR's branch: switch to `main` and pull, provided no additional local work would be lost.
- On another feature branch: keep that branch and merge the latest fetched `main` into it; resolve conflicts and validate.

**Verify the final local branch and synchronization state.** Briefly report material changes and any deferred synchronization, including its blocker and next step.

# When not to do maintenance

If your primary task is not about maintaining or reviewing PRs and branches, then this maintenance is secondary to your main task. Do only if convenient and easy. Skip maintenance if it will disrupt your active task or if you can not easily checkout the feature branch in the filesystem or in a worktree.

Always preserve local edits, unpushed commits, and checkouts used by other agents or running processes. Defer unsafe changes. If the current workspace is not clean, do not abandon changes, but advise the user about the current status of local vs remote. Recommend what to do.

---

**Self-reflection and improvement:**
Consider these instructions with your current use case. Can anything be done do to make your job easier? Can we improve these instructions to help make the task easier next time? Edit this skill `skills/pr-management` with any improvements you can think of for next time or suggest possible improvements.
