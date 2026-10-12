---
name: our-new-global-skill
description: Read and update a project's local notes so successive scheduled Codex runs know the current status, blockers and next actions.
---

# Project notes

Keep the next scheduled run informed. Use `.codex/project-coordinator/` in the
assigned project's primary checkout; keep this folder ignored by Git.

1. **Read previous status.** Open `ACTIVE.md` and the notes it links. If absent,
   create `ACTIVE.md` from the current prompt and what you can verify.
2. **Check what changed.** Check the tasks, PRs or jobs named in those notes or the
   current prompt. Record current observations; label anything you cannot check
   as unverified. The automation prompt defines any work to perform.
3. **Save updated status before finishing.** Update `ACTIVE.md` with the check
   time, what changed, what is done or still running, blockers or questions for
   the human developer, and the next action and who should take it. Keep actual
   task, PR and job links or IDs so the next run can find them.

Keep `ACTIVE.md` short and current. Put detailed findings and completed history
in dated files under `notes/`, linked from `ACTIVE.md`. Retain useful prior context;
keep credentials and raw logs out of these notes. End with a brief result and any
required human action.
