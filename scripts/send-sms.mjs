#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { parseArgs } from 'node:util';
import { chunkSms, loadSmsConfig, messageStatus, sendSms, SmsError } from './sms.mjs';

const help = `Usage: agents-sms [--dry-run] [--file PATH]
       agents-sms --check
       agents-sms --status SM...

Reads message text from stdin, or --file. Sends only to the stored recipient.
--dry-run validates configuration and reports request count without network access.
--check validates the owner-only credential profile without network access.
--status makes one read-only Twilio request for an earlier message SID.
Outputs JSON metadata, never credentials, phone numbers, or message text.
Requires Node.js >=22.18.0. No npm install required.
`;

try {
  const { values } = parseArgs({ options: {
    help: { type: 'boolean', short: 'h' },
    check: { type: 'boolean' },
    'dry-run': { type: 'boolean' },
    file: { type: 'string' },
    status: { type: 'string' },
  }});
  if (values.help || (process.argv.length === 2 && process.stdin.isTTY)) {
    process.stdout.write(help);
  } else {
    if (values.file === '' || values.status === '') throw new SmsError('invalid_options');
    if ((values.check && (values.status || values.file || values['dry-run'])) ||
        (values.status && (values.file || values['dry-run']))) throw new SmsError('invalid_options');
    const config = loadSmsConfig();
    let result;
    if (values.check) result = { ok: true, configuration: 'valid', network: false };
    else if (values.status) result = { ok: true, ...await messageStatus(values.status, config) };
    else {
      if (!values.file && process.stdin.isTTY) throw new SmsError('message_input_required');
      let message;
      try { message = readFileSync(values.file ?? 0, 'utf8'); }
      catch { throw new SmsError('message_unreadable'); }
      const chunks = chunkSms(message);
      result = values['dry-run']
        ? { ok: true, dryRun: true, requests: chunks.length, characters: [...message].length, network: false }
        : { ok: true, ...await sendSms(message, config) };
    }
    process.stdout.write(JSON.stringify(result) + '\n');
  }
} catch (error) {
  // Native parse/IO/provider errors may contain input or secrets. Print codes only.
  const code = error instanceof SmsError ? error.code : 'invalid_options_or_runtime';
  process.stderr.write(JSON.stringify({ ok: false, code, acceptedParts: error instanceof SmsError ? error.acceptedParts : 0,
    messages: error instanceof SmsError ? error.messages : [] }) + '\n');
  process.exitCode = 1;
}
