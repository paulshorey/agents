---
name: pr-management
description: Review and maintain relevant PRs, address feedback and conflicts, diagnose checks, and synchronize checkouts. Use for requested PR maintenance or follow-up needed by the active task.
---

# PR maintenance

Use [Git management](../git-management/SKILL.md) for branches, publishing, review
requests, and promotions. Requested maintenance includes routine fixes, pushes,
comments, and authorized merges. Respect repository rules and holds; preserve
local edits, unpushed commits, and active processes. Keep incidental maintenance
within the primary task's scope.

1. **Inspect.** Fetch refs and run
   `python3 ~/.agents/skills/pr-management/scripts/pr-context.py <PR_URL>`.
   Add `--diff` for code changes; see the [helper guide](../../docs/runbooks/utilities.md#pr-context).
   Inspect head/base, draft status, reviews, threads, checks, and local divergence.
   The helper fetches all feedback pages; never assume the first 30 comments are
   complete. Fast-forward with `--ff-only` where safe; investigate divergence
   rather than resetting.
2. **Review uncovered changes.** Identify which changes prior reviews covered;
   review the remaining current changes and their affected context. Treat all
   bot suggestions, including Cursor fix PRs, as proposals: verify correctness,
   scope, and validation before accepting or rejecting them. Respect user-specified
   reviewer exclusions and product/device/release holds.
3. **Address each comment.** Verify the finding, fix it, validate, commit, and push.
   **Always reply to every comment addressed by a fix or improvement**, even when
   one change addresses several comments. State what changed, the commit or
   contribution PR, and validation. Reply in the original inline thread; for
   ordinary comments or review summaries, post a PR reply linking the original.
   Verify replies were posted; commits, thread resolution, and final chat reports
   do not replace replies. Avoid repeating an already-posted response for the same
   outcome. Explain rejected findings and deferrals; leave blockers and unanswered
   questions open. Resolve inline threads only after verifying the fix and posting
   its reply. Ordinary comments cannot be resolved.
4. **Repair conflicts/checks.** Merge fetched `main` (or the PR's actual base)
   into a conflicting feature branch, resolve, and validate. Inspect failed logs
   and fix understood causes. Do not guess product decisions or leave an unfinished
   merge. Report blockers with evidence and a concrete next step.
5. **Merge when ready and authorized.** Fetch fresh PR context; recheck the exact
   head, review coverage, checks/approvals, conflicts, blockers, and replies to
   addressed comments. Respect protections and holds; your fixes do not count as
   independent review or authorize merging a same-run contribution. Verify the merge.
6. **Synchronize safely.** After merging, fast-forward a clean `main` or switch a
   clean merged-task branch to `main` and fast-forward. Preserve another active
   feature branch; integrate its base only when the task requires it. Never switch
   or reset a busy primary checkout merely because a review clone is clean.

Report material changes, PR links, validation, final local branch/synchronization,
and deferred work with its blocker. Verify each affected checkout rather than
claiming the primary one is synchronized from a temporary clone's state.
