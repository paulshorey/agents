// Adapted from ~/git/paul/src/lib/sms.ts. No npm dependencies or app runtime.
import { constants, openSync, closeSync, readFileSync, fstatSync, statSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { homedir } from 'node:os';
import { parseEnv } from 'node:util';
import { fileURLToPath } from 'node:url';

export const ROOT = fileURLToPath(new URL('../', import.meta.url));
export class SmsError extends Error {
  constructor(code, acceptedParts = 0) {
    super('SMS operation failed.');
    this.code = code;
    this.acceptedParts = acceptedParts;
    this.messages = [];
  }
}

export function readSmsConfig(env) {
  const accountSid = env.TWILIO_ACCOUNT_SID ?? '';
  const useApiKey = Boolean(env.TWILIO_API_KEY_SID || env.TWILIO_API_KEY_SECRET);
  const username = useApiKey ? env.TWILIO_API_KEY_SID ?? '' : accountSid;
  const password = (useApiKey ? env.TWILIO_API_KEY_SECRET : env.TWILIO_AUTH_TOKEN) ?? '';
  const from = env.TWILIO_FROM_NUMBER ?? '';
  const to = env.TWILIO_TO_NUMBER ?? '';
  if (!/^AC[0-9a-f]{32}$/i.test(accountSid) || !password ||
      (useApiKey && !/^SK[0-9a-f]{32}$/i.test(username)) ||
      !/^\+[1-9]\d{7,14}$/.test(from) || !/^\+[1-9]\d{7,14}$/.test(to)) {
    throw new SmsError('configuration_missing');
  }
  return { accountSid, username, password, from, to };
}

export function profilePath(root = ROOT) {
  try {
    const profile = JSON.parse(readFileSync(resolve(root, 'config/profiles.json'), 'utf8')).profiles['twilio.sms'];
    if (profile.provider !== 'twilio' || typeof profile.path !== 'string' ||
        !(profile.path.startsWith('~/') || profile.path.startsWith('/'))) throw new Error();
    return profile.path.startsWith('~/') ? resolve(homedir(), profile.path.slice(2)) : profile.path;
  } catch { throw new SmsError('profile_catalog_invalid'); }
}

export function loadSmsConfig(path = profilePath()) {
  let fd;
  try {
    const parent = statSync(dirname(path));
    fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    const info = fstatSync(fd);
    if (!info.isFile() || info.uid !== process.getuid() || (info.mode & 0o777) !== 0o600 ||
        parent.uid !== process.getuid() || (parent.mode & 0o777) !== 0o700) {
      throw new SmsError('profile_permissions');
    }
    // Literal dotenv parsing; no shell evaluation or inherited credential overrides.
    return readSmsConfig(parseEnv(readFileSync(fd, 'utf8')));
  } catch (error) {
    if (error instanceof SmsError) throw error;
    throw new SmsError('profile_unreadable');
  } finally { if (fd !== undefined) closeSync(fd); }
}

export function chunkSms(message) {
  if (typeof message !== 'string' || !message.trim()) throw new SmsError('empty_message');
  if (!message.isWellFormed()) throw new SmsError('invalid_unicode');
  if (message.length > 5600) throw new SmsError('message_too_long');
  const chunks = [];
  let chunk = '';
  for (const character of message) {
    if (chunk.length + character.length > 1400) {
      chunks.push(chunk);
      chunk = '';
    }
    chunk += character;
  }
  if (chunk) chunks.push(chunk);
  if (chunks.length > 4) throw new SmsError('message_too_long');
  return chunks.map((body, i) => chunks.length > 1 ? `${body}\n[Page: ${i + 1} of ${chunks.length}]` : body);
}

async function twilio(config, suffix, options, request, acceptedParts = 0) {
  try {
    const response = await request(`https://api.twilio.com/2010-04-01/Accounts/${config.accountSid}/${suffix}`, {
      ...options,
      headers: {
        Authorization: `Basic ${Buffer.from(`${config.username}:${config.password}`).toString('base64')}`,
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      redirect: 'error',
      signal: AbortSignal.timeout(8000),
      cache: 'no-store',
    });
    const data = await response.json();
    if (!response.ok) throw new SmsError(typeof data?.code === 'number' ? String(data.code) : `http_${response.status}`, acceptedParts);
    return data;
  } catch (error) {
    if (error instanceof SmsError) throw error;
    // A failed response/timeout may follow acceptance; never automatically retry.
    throw new SmsError('request_failed', acceptedParts);
  }
}

export async function sendSms(message, config, dependencies = {}) {
  const request = dependencies.fetch ?? fetch;
  const pause = dependencies.pause ?? ((ms) => new Promise((r) => setTimeout(r, ms)));
  const now = dependencies.now ?? Date.now;
  const chunks = chunkSms(message);
  const messages = [];
  for (const body of chunks) {
    const started = now();
    let data;
    try {
      data = await twilio(config, 'Messages.json', {
        method: 'POST', body: new URLSearchParams({ To: config.to, From: config.from, Body: body }),
      }, request, messages.length);
      if (!/^SM[0-9a-f]{32}$/i.test(data?.sid) ||
          !['queued', 'accepted', 'sending', 'sent', 'delivered'].includes(data?.status)) {
        throw new SmsError('not_accepted', messages.length);
      }
    } catch (error) {
      // Preserve receipts for earlier parts even when a later request fails.
      error.messages = [...messages];
      throw error;
    }
    messages.push({ sid: data.sid, status: data.status });
    if (messages.length < chunks.length) await pause(Math.max(0, 10000 - (now() - started)));
  }
  return { acceptedParts: messages.length, messages };
}

export async function messageStatus(sid, config, request = fetch) {
  if (!/^SM[0-9a-f]{32}$/i.test(sid)) throw new SmsError('invalid_message_sid');
  const data = await twilio(config, `Messages/${sid}.json`, { method: 'GET' }, request);
  const statuses = ['accepted', 'scheduled', 'queued', 'sending', 'sent', 'delivered', 'undelivered', 'failed', 'canceled', 'read'];
  if (data?.sid !== sid || !statuses.includes(data?.status)) throw new SmsError('invalid_status_response');
  if (data.to !== config.to || data.from !== config.from) throw new SmsError('message_target_mismatch');
  return { sid, status: data.status, errorCode: typeof data.error_code === 'number' ? data.error_code : null };
}
