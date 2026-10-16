# Agent SMS

`~/.agents/bin/agents-sms` sends to Paul's fixed recipient using Twilio's Messages
REST API. It is independent of `~/git/paul`, npm packages, a web service, and MCP.
The transport was adapted from `~/git/paul/src/lib/sms.ts`, retaining API-key/Auth
Token authentication, safe chunking, eight-second request timeouts, sequential
sending, and no automatic retries. This copy is maintained here; Paul remains
responsible for its contact form.

## Use from an agent or terminal

Invoke `$send-sms` in Codex with a message or notification request, for example:

```text
$send-sms Text me when this task is finished, including the PR URL.
```

The skill is installed directly under `~/.agents/skills/send-sms`. Manual invocation
and ordinary skill selection are supported. Existing chats may need a fresh
session to discover it; an agent can also read the skill by its absolute path.
OpenAI documents skill discovery and invocation in
[Build skills](https://learn.chatgpt.com/docs/build-skills).

Any local agent with terminal access can call the absolute command:

```sh
~/.agents/bin/agents-sms --check
~/.agents/bin/agents-sms --dry-run <<'SMS'
Example task completed. Review the PR when convenient.
SMS
~/.agents/bin/agents-sms <<'SMS'
Example task completed. Review the PR when convenient.
SMS
```

`--file /absolute/path/message.txt` replaces stdin. Quoted heredocs preserve shell
metacharacters; choose a delimiter absent from the message. Commands do not accept
recipient overrides or message text as arguments. JSON output omits credentials,
phone numbers, and message bodies. The existing `config/env.sh` PATH hook exposes
`agents-sms` to new login shells; the absolute path works without that hook.

Node >=22.18.0 is required. The helper works on this local Mac from any repository
or worktree. Remote/cloud agents require separate authorized provisioning and
access to the command and profile; a public clone carries no credentials. Existing
sandbox, network, and approval restrictions still apply. The setup does not add a
public endpoint, background watcher, recurring automation, or native permission rule.

## Credential ownership and recovery

`config/profiles.json` owns the `twilio.sms` profile's location:
`~/.agents/local/credentials/twilio-sms.env`. The credential file must be owned by
the current user with mode 600, in a mode-700 owner-owned directory. `local/` is
ignored. The loader rejects symlinked credential files and reads literal dotenv
assignments without shell evaluation. It loads only the selected file; inherited
Twilio variables cannot override the sender, recipient, or credential.

Supported variable names:

| Variable | Purpose |
| --- | --- |
| `TWILIO_ACCOUNT_SID` | Account that owns the sender |
| `TWILIO_AUTH_TOKEN` | Existing account token, when API-key variables are absent |
| `TWILIO_API_KEY_SID`, `TWILIO_API_KEY_SECRET` | Optional API-key pair replacing the token |
| `TWILIO_FROM_NUMBER`, `TWILIO_TO_NUMBER` | Fixed sender and Paul's recipient, in E.164 format |

On 2026-10-16, initial setup copied only the required Twilio assignments from
`~/git/paul/.env.local`. That working source used an account Auth Token, not a
separate API key. No account grants or credentials were rotated. The source file
and the Paul application remain independently maintained; later rotations are not
automatically synchronized.

To initialize a missing profile from an authorized existing dotenv file:

```sh
node ~/.agents/scripts/import-sms-profile.mjs ~/git/paul/.env.local
~/.agents/bin/agents-sms --check
```

The importer validates configuration, copies only the active Twilio credential
method and numbers, sets private permissions, and refuses to overwrite an existing
profile. It does not source the input or print values. For rotation, securely edit
the registered file locally, preserving literal assignments and mode 600; do not
put values in shell arguments, chat, documentation, diffs, or Git. Coordinate the
independent Paul copy before revoking a shared token. An API key's permissions must
cover the intended operations; a key restricted to sending may not permit status
reads. This task did not narrow existing account grants.

Run `git check-ignore ~/.agents/local/credentials/twilio-sms.env` and `--check`
after provisioning. Neither check establishes provider authentication or delivery.
`agents-config check` checks registered required variable names and private file
permissions; the SMS helper additionally validates the active authentication pair
and number formats. Generic `agents-config check --live` does not send SMS or test
Twilio. An explicitly authorized test send verifies the transport.

Initial live verification on 2026-10-16 sent exactly one user-approved setup-test
SMS through `agents-sms`. Twilio accepted one request and the subsequent status
read reported `delivered` with no error code. This is dated evidence, not a
guarantee of future credential validity or carrier delivery.

## Results, failures, and delivery

A successful send returns `acceptedParts` and message `sid`/`status` metadata.
Each request can still use multiple billable SMS segments. Up to four requests of
1,400 UTF-16 units each are sent sequentially, at least ten seconds apart, with
page labels for multipart input. Overflow and whitespace-only input fail before
network access. Grapheme boundaries, including joined emoji and combining marks,
are preserved; a single cluster longer than 1,400 UTF-16 units is rejected with
`grapheme_too_long` before sending. Prefer short notifications.

Acceptance and final delivery differ, as documented in Twilio's
[Messages resource](https://www.twilio.com/docs/messaging/api/message-resource).
To inspect an earlier send without sending again:

```sh
~/.agents/bin/agents-sms --status SM_REPLACE_WITH_RETURNED_MESSAGE_SID
```

The status read verifies the configured sender/recipient and outputs only SID,
status, and numeric error code. `delivered` is Twilio's carrier delivery report;
`sent`/`queued` is not delivery confirmation. Status checks are one-shot reads.

Errors exit nonzero with sanitized `code` and `acceptedParts`. A partial failure
reports how many earlier requests were accepted and preserves their SID/status
receipts in `messages`. Timeouts or invalid responses
may follow acceptance of the current request. The helper never retries a send;
inspect Twilio's console or known SIDs before deciding whether to resend. Provider
error text and response bodies are not logged. The helper stores no message body,
delivery journal, or credential status report; Twilio retains its own records.

## Validate changes

```sh
node --test ~/.agents/tests/sms.test.mjs
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py ~/.agents/skills/send-sms
~/.agents/bin/agents-config validate
~/.agents/bin/agents-config docs
~/.agents/bin/agents-config docs --check
git -C ~/.agents diff --check
```

Tests use synthetic credentials and local HTTP responses. They never contact
Twilio or send a real SMS. Live sends require a user-requested message or an
authorized notification/test.
