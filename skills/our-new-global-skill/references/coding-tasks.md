# Native coding-task helper

Read this only when the current automation prompt calls for creating or managing
Codex desktop coding tasks. Routine note updates use SKILL.md alone.

Use Python 3.11+ and `scripts/tasks.py --cwd PRIMARY_PROJECT --repository OWNER/REPO`
with the absolute script path. The helper keeps records in the primary project's
ignored `.codex/project-coordinator`; linked worktrees share them.

1. Run `doctor` and `tasks`; inspect the recorded native threads and existing PRs
   before creating work. Run `begin` to claim a coordination pass. Thread identity
   defaults to CODEX_THREAD_ID. If another pass owns it, read that owner's actual
   thread. Use `end --recovered` only with confirmed recovery evidence, never age.
2. Use native list_projects and `bind --project-id ID` for the verified local project.
   Save a scoped prompt in the private folder. Run `task-prepare --scope NAME
   --base FULL_SHA --prompt FILE --authority HUMAN_REQUEST --acceptance CHECKS`.
   An existing scope is reconciled instead of submitted again.
3. Run `task-claim --task ID --pass-id PASS`, then `dispatch-plan --task ID`.
   Submit the returned native create_thread arguments once. The child's included
   task-start command checks its actual thread, linked worktree, origin, base and
   cleanliness before edits. Save a ready thread with `task-attach --task ID
   --thread READY_ID`; pending IDs are not ready IDs. Resolve unknown creation
   outcomes through the ledger and native task history before retrying.
4. Read the actual task; use `task-observe --task ID --status STATUS --evidence NOTE`.
   Verify the current diff, checks and PR head before adding `--close`.
   Follow-ups need the saved prompt's human grant, matching ownership and approved
   scope. Read newer human messages first; resolve a lost send response before retrying.
5. Release the pass with `end --pass-id PASS --evidence NOTE`, including blocked
   outcomes. An interrupted pass retains its claim for later recovery.

Coding model defaults live in scripts/task_state.py; the coordinator's model is
selected in Codex. Keep existing human work and live worktrees intact.
