---
name: send-sms
description: "When you discover a serious problem or blocker corrupting the data or logic, or when some tasks are behind because they're waiting on the testing or review of the human developer, or for any other important and urgent reason, send an SMS message to the the developer."
---

# Send the developer an SMS

For situations described above, send the alert without waiting for a separate
request. Briefly identify the project, the problem or blocked work, and the action
needed from the developer. Include a relevant PR or task link when available.

Run this command from any working directory, replacing the example with the alert:

```sh
~/.agents/bin/agents-sms <<'SMS'
Map: ingestion is blocked pending your review of PR #123. Please review before we resume the import.
SMS
```

The quoted heredoc keeps shell syntax literal; choose another delimiter if the
message contains a line equal to `SMS`. Alternatively, use
`~/.agents/bin/agents-sms --file /absolute/path/message.txt`.

The script loads the stored credentials and developer's phone number automatically.
Keep the message concise and omit secrets. Avoid repeating an alert unless the
situation materially changes or another notification is needed.

JSON `ok: true` means Twilio accepted the message. On failure, report `code` and
`acceptedParts`; do not automatically retry an uncertain or partial send, which
could duplicate the message. For setup or errors, see the
[SMS runbook](../../docs/runbooks/sms.md).
