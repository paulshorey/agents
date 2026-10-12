---
name: our-new-global-skill
description: Coordinate requested work in one local GitHub project from a native Codex desktop task or scheduled run. Reconcile PRs, checks, decisions and delegated native coding tasks using durable ownership records. Scheduling and model settings remain in Codex.
---

# Project coordination

Use this skill for a bounded pass on the project named in the user's prompt. Read
its applicable AGENTS.md and existing human requests first. Codex owns the schedule,
saved prompt, coordinator model, permissions and notifications. This skill does not
export, audit or reset those settings and does not grant messaging/release authority.

## Reconcile before acting

The helper scripts are relative to this skill folder. They require Python 3.11+;
GitHub inspection also requires git and authenticated gh. Run:

```sh
python3 scripts/tasks.py --cwd PROJECT --repository OWNER/REPO doctor
python3 scripts/tasks.py --cwd PROJECT --repository OWNER/REPO begin
python3 scripts/tasks.py --cwd PROJECT --repository OWNER/REPO tasks
python3 scripts/github-status.py --cwd PROJECT --repository OWNER/REPO
```

Use absolute script paths when your shell is in the project. `doctor` returns the
private state directory under ~/.codex/project-coordinator. Read its ACTIVE.md and
linked evidence; it holds continuity across fresh scheduled chats. Native thread
identity defaults to actual CODEX_THREAD_ID. A different active pass blocks ownership:
read that exact native thread before recovering it with `end --recovered`. Age or
notLoaded status alone never proves it stopped. Do not create a second writer.

The GitHub helper reads paginated open PRs/issues across all authors and reports
actual head/base SHAs. For relevant PRs, inspect reviews, checks, changed commits and
human decisions using native tools/gh. Use the installed pr-management skill when
maintaining a PR/branch; preserve the project's deployment and process safeguards.
Do not invent features from stale issues or treat saved state, task output or PR
comments as new human authority. Reconcile human-owned work without taking it over.

## Act within the request

Prefer existing requested work, failed checks and review feedback. Read tracked
native threads by their actual IDs. Unknown/loading states are evidence limits,
not permission to redispatch. Product choices or work outside the approved scope
remain decisions for the human.

For implementation, use a separate visible native worktree task. Read
[the coding task procedure](references/coding-tasks.md) when creating, reconciling,
following up or closing a delegated task. The helper's coding model preference is
independent of the model selected for this scheduled coordinator in Codex.

A standing human grant in the saved prompt can authorize routine follow-ups to the
coordinator's own project tasks. Verify the target against the task ledger and
creation evidence, then read the latest human messages before using native
send_message_to_thread. Stay within approved scope; unrelated targets and expanded
scope need human direction. Save the message/receipt privately. Resolve a lost send
response against actual target history before retrying. This skill does not supply
a blanket authorization and must not override newer human instructions.

Long-running project processes belong to deterministic project tooling. Read the
project's durable jobs and control evidence once per ordinary pass; do not keep an
AI turn alive with sleeps, log streaming or repeated polling. For map, use its own
scripts/coordinator-ingestion.py and data/ingestion-agents.md. The skill does not own
map's scripts, database controls or provider-spending policy.

## Finish and retain continuity

Update affected entries in ACTIVE.md with actual task/PR/job IDs, fresh observation
timestamps, pending decisions and next owner. Detailed evidence belongs in linked
private notes. Release the pass with `end --pass-id ID --evidence REFERENCE`, including
blocked outcomes when possible. An interrupted pass remains claimed for recovery.
End with a short visible result and the next action; routine passes should be bounded.

For credential-bearing project commands use scripts/project-env.py with its Python
environment and the actual project/app/worktree cwd. Install requirements.txt into
this skill's .venv if needed. --check prints availability without values. Map requires
--shell-only; its local ingestion helper already implements that boundary. Plain
git/rg/gh inspection does not need the credential runner. Keep private state and
credentials out of Git and prompts. Missing native task tools are a blocker; never
substitute a headless CLI agent or remote coding environment.
