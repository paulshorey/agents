#!/usr/bin/env node
// Explicit local migration. Never prints source data or overwrites a profile.
import { readFileSync, mkdirSync, chmodSync, openSync, writeFileSync, closeSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { parseEnv } from 'node:util';
import { profilePath, readSmsConfig } from './sms.mjs';

try {
  if (process.argv.length !== 3) throw new Error();
  const source = parseEnv(readFileSync(resolve(process.argv[2]), 'utf8'));
  readSmsConfig(source);
  const names = ['TWILIO_ACCOUNT_SID', 'TWILIO_FROM_NUMBER', 'TWILIO_TO_NUMBER',
    ...(source.TWILIO_API_KEY_SID || source.TWILIO_API_KEY_SECRET
      ? ['TWILIO_API_KEY_SID', 'TWILIO_API_KEY_SECRET'] : ['TWILIO_AUTH_TOKEN'])];
  const content = names.map((name) => {
    const value = source[name];
    if (!/^[A-Za-z0-9+_-]+$/.test(value)) throw new Error();
    return `${name}=${value}\n`;
  }).join('');
  const destination = profilePath();
  mkdirSync(dirname(destination), { recursive: true, mode: 0o700 });
  chmodSync(dirname(destination), 0o700);
  const fd = openSync(destination, 'wx', 0o600);
  try { writeFileSync(fd, content); } finally { closeSync(fd); }
  console.log(JSON.stringify({ ok: true, profile: 'twilio.sms', copiedVariables: names }));
} catch {
  console.error(JSON.stringify({ ok: false, code: 'import_failed', hint: 'Supply one valid dotenv source path; destination must not exist. Inspect files locally without displaying values.' }));
  process.exitCode = 1;
}
