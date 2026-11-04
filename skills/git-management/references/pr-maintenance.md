# PR maintenance

Read the owning [Git and PR workflow](../SKILL.md) first. Requested maintenance
includes routine fixes, pushes, replies, and authorized merges. Keep incidental
maintenance within the primary task's scope.

1. **Inspect.** Fetch refs and complete PR context; inspect head/base, draft status,
   reviews, unresolved threads, checks, and local divergence. Fast-forward with
   `--ff-only` where safe; investigate divergence rather than resetting.
2. **Review uncovered changes.** Identify the commits prior reviews covered and
   inspect the remaining changes and affected context at the current head. Treat
   bot suggestions and fix PRs as proposals. Respect reviewer exclusions and
   product/device/release holds. Report actionable concerns in a PR comment unless
   fixing them immediately. Use the [review loop](review-loop.md) for fixes and
   per-comment replies; your fixes do not count as independent review.
3. **Repair conflicts/checks.** Merge the fetched actual base into a conflicting
   feature branch, resolve, and validate. Inspect failed check logs and fix
   understood causes. Do not guess product decisions or leave an unfinished merge.
   Report blockers with evidence and a concrete next step.
4. **Merge only when ready and authorized.** Fetch fresh context; recheck the
   exact head, review coverage, checks/approvals, conflicts, substantive blockers,
   replies, protections, and holds. A clean review does not authorize a merge or
   automatically allow merging a same-run contribution. Verify the merge result.
5. **Synchronize safely.** After merging, fast-forward a clean `main`, or switch a
   clean merged-task branch to `main` and fast-forward. Preserve other active
   feature branches; integrate their base only when required. Never switch/reset
   a busy primary checkout merely because a review clone is clean. Verify each
   affected checkout before reporting its final branch and synchronization.
