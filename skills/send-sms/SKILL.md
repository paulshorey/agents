---
name: send-sms
description: Send an SMS to Paul's configured phone through the shared local Twilio command. Use for a requested text message or an explicitly authorized SMS notification when work completes or needs attention.
---

# Send Paul an SMS

Run `~/.agents/bin/agents-sms` from any working directory on this Mac. The helper
loads the registered owner-only profile itself; never read, echo, source, or pass
credentials or phone numbers in commands. Node >=22.18.0 and outbound HTTPS to
Twilio are required. No Paul application, web server, npm install, or MCP is needed.

The user's request to send a text or notify them by SMS authorizes that message;
carry it out without asking again. For future notifications, send at the requested
milestone with concise context about the project and outcome. Invoking this skill
alone without a message or purpose calls for a focused clarification. Access to
the command does not authorize unsolicited texts or messages to other people.

Pass text using a quoted heredoc so shell syntax in the message stays literal:

```sh
~/.agents/bin/agents-sms <<'SMS'
Paul deployment finished. Production health checks passed.
SMS
```

For a file, use `~/.agents/bin/agents-sms --file /absolute/path/message.txt`.
`--dry-run` with either input validates locally without sending; `--check` checks
credential configuration only. Use a different heredoc delimiter if the message
contains a line equal to `SMS`.

Keep messages concise. The helper supports at most four labeled API requests of
1,400 UTF-16 units each, preserves emoji, and rejects overflow without truncation.
Twilio may bill multiple carrier segments per request. Avoid credentials or private
logs in the text. The recipient and sender come exclusively from the profile.

Read the JSON result. `ok: true` on a send means Twilio accepted every part. Report
acceptance accurately; carrier delivery is asynchronous. Check a returned SID with
`~/.agents/bin/agents-sms --status SM...` when delivery confirmation is needed.

On failure, stop and report `code` and `acceptedParts`. A timeout, malformed
response, or partial failure can leave messages already accepted. Do not retry the
whole message automatically; inspect known message SIDs or ask before resending
when the outcome is uncertain. Never display raw provider responses.

For credential setup, rotation, or runtime trouble, consult the
[SMS runbook](../../docs/runbooks/sms.md). Sandboxed or remote agents still need
their own authorized filesystem/network access and credential provisioning.
