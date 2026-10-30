---
name: pr-management
description: Review and maintain relevant PRs, address feedback and conflicts, diagnose checks, and synchronize checkouts. Use for requested PR maintenance or follow-up needed by the active task.
---

# PR maintenance

Use [Git management](../git-management/SKILL.md) for branches, publishing, review
requests, and production promotions. Work within current authorization and
repository rules; preserve local edits, unpushed commits, and active processes.
Incidental maintenance must not disrupt or expand the primary task.

1. **Establish current state.** Fetch refs and inspect PR head/base, draft status,
   reviews, unresolved threads, checks, and local divergence. Fast-forward with
   `--ff-only` where safe; investigate divergence rather than resetting.
2. **Review uncovered changes.** Identify which changes prior reviews covered;
   review the remaining current changes and their affected context. Treat all
   bot suggestions, including Cursor fix PRs, as proposals: verify correctness,
   scope, and validation before accepting or rejecting them. Respect user-specified
   reviewer exclusions and product/device/release holds.
3. **Address feedback.** Fix valid findings, validate, commit, push, and reply
   with the outcome. Explain false positives or justified deferrals; resolve
   handled inline threads only after verification. Leave genuine blockers and
   undecided questions open. Ordinary comments cannot be resolved. Avoid duplicate
   replies; link contribution PRs and record actionable concerns not fixed directly.
4. **Repair conflicts/checks.** Merge fetched `main` (or the PR's actual base)
   into a conflicting feature branch, resolve, and validate. Inspect failed logs
   and fix understood causes. Do not guess product decisions or leave an unfinished
   merge. Report blockers with evidence and a concrete next step.
5. **Merge only when ready and authorized.** Recheck the exact head, review coverage,
   required checks/approvals, conflicts, and substantive blockers. Respect protections
   and holds; do not treat your own fixes as independent review or automatically
   merge a same-run contribution. Verify the merge result.
6. **Synchronize safely.** After merging, fast-forward a clean `main` or switch a
   clean merged-task branch to `main` and fast-forward. Preserve another active
   feature branch; integrate its base only when the task requires it. Never switch
   or reset a busy primary checkout merely because a review clone is clean.

Report material changes, PR links, validation, final local branch/synchronization,
and deferred work with its blocker. Verify each affected checkout rather than
claiming the primary one is synchronized from a temporary clone's state.
