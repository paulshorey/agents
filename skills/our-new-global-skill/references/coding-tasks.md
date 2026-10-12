# Native coding tasks and ownership

Use scripts/tasks.py with --cwd PRIMARY_PROJECT and --repository OWNER/REPO.
Review origin, project guides, native project/path and the exact committed base.
Native worktree creation defaults to the repository's default branch; the child
must stop if it starts at a different base. Do not reset human changes to satisfy
admission. A deliberately different starting state requires a reviewed native
request and a consistent ledger base.

1. Reconcile existing scopes, native tasks, PRs and worktrees before creating work.
   Put a narrow prompt in the private state directory returned by doctor.
2. `task-prepare --scope STABLE_SCOPE --base FULL_SHA --prompt PRIVATE_FILE
   --authority HUMAN_REQUEST --acceptance CHECKS` freezes the request and deduplicates
   its scope. An existing intent is reconciled, not resubmitted.
3. Use native list_projects and bind the actual local project with
   `bind --project-id ID`. Verify its path/host. Ensure native create/read task tools
   are available before `task-claim --task ID --pass-id PASS`.
4. `dispatch-plan --task ID` emits structured native create_thread arguments.
   Submit once. It requests a separate worktree and an independent coding model;
   it does not invoke an agent itself. Save a ready thread with
   `task-attach --task ID --thread READY_ID`. Pending client IDs are not ready IDs.
5. The child's first `task-start --task ID --actual-cwd ACTUAL_CWD` registers its
   actual thread and checks linked-worktree identity, origin, base and clean state
   before any edit. Even failed admission records the thread for discovery.
   Inspect the ledger first if creation returned a pending ID. Persist other native
   operation/client IDs in private evidence, then use supported native discovery.
   Unknown submission or timeout retains the claim; never retry blindly.
6. Read the actual task and preserve opaque statuses. Record fresh observations with
   `task-observe --task ID --status STATUS --evidence REFERENCE`. A final message
   alone is not verification. Inspect the diff, relevant checks and actual PR head
   before `task-observe --close`; changed PR heads invalidate earlier results.

Routine follow-ups require the applicable human grant from the task/scheduled
prompt. The exact target must be a task this project coordinator created, within
its approved scope. Other conversations remain human-owned. Keep one writer per
worktree; do not delete worktrees/branches with live tasks, changes or unmerged work.

Coding defaults are DEFAULT_CODING_MODEL and DEFAULT_CODING_REASONING in
scripts/task_state.py (currently GPT-6.1 Sol / High). Change only those preferences
when intentionally changing delegated coding. Changing the coordinator's model in
Codex does not change these defaults. Existing children retain their settings.
Account, Standard/Fast speed and permissions remain native app controls; the helper
cannot prove or override them. No extra coordinator model registry is maintained.
