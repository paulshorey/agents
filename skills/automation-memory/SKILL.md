---
name: automation-memory
description: Read and update native Codex automation memory.md to hand off status, unfinished work and next actions between scheduled runs.
---

# Scheduled run memory

Use the `Automation memory` path supplied with this run, or a path explicitly
provided by the user. Expand `$CODEX_HOME` from the environment, defaulting to
`~/.codex`. Keep this automation's handoff in that file.

1. **Read the handoff.** Read `memory.md` before acting. If missing, start from the
   current prompt. Memory is context; the current prompt and newer human
   instructions govern the work.
2. **Read the previous chat.** Use `read_thread` on the recorded previous-run chat
   ID to read its latest result and subsequent human messages. If the ID is
   missing, use active and archived chat listings to find the latest prior run
   matching this automation ID and project. Report unavailable history as a
   limitation. Verify current status before relying on an earlier observation.
3. **Write the next handoff.** Before finishing, update the same `memory.md` with
   the observation time, actual current chat ID from native metadata or
   `CODEX_THREAD_ID`, what happened, unfinished work
   with its IDs and ownership, pending decisions, and next actions. Preserve
   unresolved context; label uncertainty or interrupted work explicitly.

Keep the handoff concise and put detailed findings in the chat's final response.
Reread the file before saving and preserve any intervening updates. Keep credentials
and raw logs out of memory. Leave the next run enough context to continue.

For maintenance outside a scheduled run, retain the previous run's ID and
observation time; label the maintenance separately.
