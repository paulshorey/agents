import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtempSync, mkdirSync, writeFileSync, chmodSync, symlinkSync, rmSync, copyFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { chunkSms, readSmsConfig, loadSmsConfig, sendSms, messageStatus, SmsError, ROOT } from '../scripts/sms.mjs';

const accountSid = `AC${'0'.repeat(32)}`;
const sid = `SM${'1'.repeat(32)}`;
const env = { TWILIO_ACCOUNT_SID: accountSid, TWILIO_AUTH_TOKEN: 'synthetic-token',
  TWILIO_FROM_NUMBER: '+15550101234', TWILIO_TO_NUMBER: '+15550105678' };
const config = readSmsConfig(env);
const dotenv = Object.entries(env).map(([k, v]) => `${k}=${v}\n`).join('');
const hasCode = (code, parts = 0) => (e) => e instanceof SmsError && e.code === code && e.acceptedParts === parts;

async function withServer(handler, run) {
  const requests = [];
  const server = createServer(async (req, res) => {
    let body = '';
    for await (const chunk of req) body += chunk;
    requests.push({ method: req.method, url: req.url, headers: req.headers, body });
    const result = handler(requests.at(-1), requests.length);
    res.writeHead(result.status ?? 201, { 'Content-Type': 'application/json' });
    res.end(typeof result.data === 'string' ? result.data : JSON.stringify(result.data));
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  // Exercise real Node fetch/HTTP and transport options using synthetic auth.
  const request = (url, options) => {
    const parsed = new URL(url);
    assert.equal(parsed.origin, 'https://api.twilio.com');
    return fetch(`http://127.0.0.1:${server.address().port}${parsed.pathname}`, options);
  };
  try { await run(request, requests); }
  finally { server.closeAllConnections(); await new Promise((r) => server.close(r)); }
}

test('account tokens and complete API key pairs; partial keys fail closed', () => {
  assert.equal(config.username, accountSid);
  assert.equal(readSmsConfig({ ...env, TWILIO_API_KEY_SID: `SK${'2'.repeat(32)}`, TWILIO_API_KEY_SECRET: 'key-secret' }).password, 'key-secret');
  assert.throws(() => readSmsConfig({ ...env, TWILIO_API_KEY_SID: `SK${'2'.repeat(32)}` }), hasCode('configuration_missing'));
  assert.throws(() => readSmsConfig({ ...env, TWILIO_TO_NUMBER: 'invalid' }), hasCode('configuration_missing'));
});

test('chunks preserve Unicode and all text; reject empty and overflow', () => {
  const message = 'x'.repeat(1399) + '🙂'.repeat(1000) + 'end';
  const chunks = chunkSms(message);
  assert.ok(chunks.every((c) => c.isWellFormed() && c.length < 1500));
  assert.equal(chunks.map((c) => c.replace(/\n\[Page: \d+ of \d+\]$/, '')).join(''), message);
  assert.equal(chunkSms('a'.repeat(5600)).length, 4);
  assert.throws(() => chunkSms('a'.repeat(5601)), hasCode('message_too_long'));
  assert.throws(() => chunkSms(' \n'), hasCode('empty_message'));
  assert.throws(() => chunkSms('\ud800'), hasCode('invalid_unicode'));
});

test('owner-only literal profile; rejects broad modes and symlinks', () => {
  const dir = mkdtempSync(join(tmpdir(), 'agents-sms-'));
  const path = join(dir, 'sms.env');
  try {
    chmodSync(dir, 0o700);
    writeFileSync(path, dotenv, { mode: 0o600 });
    assert.deepEqual(loadSmsConfig(path), config);
    chmodSync(path, 0o644);
    assert.throws(() => loadSmsConfig(path), hasCode('profile_permissions'));
    chmodSync(path, 0o600);
    chmodSync(dir, 0o755);
    assert.throws(() => loadSmsConfig(path), hasCode('profile_permissions'));
    chmodSync(dir, 0o700);
    symlinkSync(path, join(dir, 'link.env'));
    assert.throws(() => loadSmsConfig(join(dir, 'link.env')), hasCode('profile_unreadable'));
    writeFileSync(path, dotenv.replace('synthetic-token', '"$(touch should-not-run)"'));
    assert.equal(loadSmsConfig(path).password, '$(touch should-not-run)');
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test('real HTTP sends fixed numbers, encoded text and auth, sequentially', async () => {
  const pauses = [];
  await withServer(() => ({ data: { sid, status: 'queued' } }), async (request, calls) => {
    const result = await sendSms('a&🙂'.repeat(800), config, { fetch: request, pause: async (ms) => pauses.push(ms), now: () => 0 });
    assert.equal(result.acceptedParts, 3);
    assert.deepEqual(pauses, [10000, 10000]);
    for (const call of calls) {
      assert.equal(call.method, 'POST');
      assert.equal(call.url, `/2010-04-01/Accounts/${accountSid}/Messages.json`);
      assert.equal(call.headers.authorization, `Basic ${Buffer.from(`${accountSid}:synthetic-token`).toString('base64')}`);
      const body = new URLSearchParams(call.body);
      assert.equal(body.get('To'), config.to);
      assert.equal(body.get('From'), config.from);
      assert.ok(body.get('Body').includes('a&🙂'));
    }
  });
});

test('partial HTTP rejection reports accepted parts, stops, and hides provider details', async () => {
  await withServer((_req, count) => count === 1 ? { data: { sid, status: 'queued' } } :
    { status: 429, data: { code: 20429, message: 'sensitive-provider-details' } }, async (request, calls) => {
    await assert.rejects(sendSms('a'.repeat(3000), config, { fetch: request, pause: async () => {} }), (error) => {
      assert.ok(hasCode('20429', 1)(error));
      assert.deepEqual(error.messages, [{ sid, status: 'queued' }]);
      return true;
    });
    assert.equal(calls.length, 2);
  });
});

test('malformed HTTP response and failed status are never retried', async () => {
  for (const data of ['<html>provider failure</html>', { sid, status: 'failed' }, null]) {
    await withServer(() => ({ data }), async (request, calls) => {
      await assert.rejects(sendSms('Hello', config, { fetch: request }), SmsError);
      assert.equal(calls.length, 1);
    });
  }
});

test('ambiguous network errors never retry', async () => {
  let calls = 0;
  await assert.rejects(sendSms('Hello', config, { fetch: async () => { calls++; throw new Error('secret'); } }), hasCode('request_failed'));
  assert.equal(calls, 1);
});

test('delivery status is a GET and returns only safe metadata for configured recipient', async () => {
  await withServer(() => ({ status: 200, data: { sid, status: 'delivered', error_code: null, to: config.to, from: config.from, body: 'private' } }), async (request, calls) => {
    assert.deepEqual(await messageStatus(sid, config, request), { sid, status: 'delivered', errorCode: null });
    assert.equal(calls[0].method, 'GET');
  });
  await withServer(() => ({ status: 200, data: { sid, status: 'sent', to: '+15550109999', from: config.from } }), async (request) => {
    await assert.rejects(messageStatus(sid, config, request), hasCode('message_target_mismatch'));
  });
});

test('isolated CLI import, check and dry-run preserve secrets and ignore inherited variables', () => {
  const dir = mkdtempSync(join(tmpdir(), 'agents-sms-cli-'));
  try {
    for (const name of ['scripts', 'config', 'private']) mkdirSync(join(dir, name), { mode: 0o700 });
    for (const name of ['sms.mjs', 'send-sms.mjs', 'import-sms-profile.mjs']) copyFileSync(join(ROOT, 'scripts', name), join(dir, 'scripts', name));
    const path = join(dir, 'private', 'sms.env');
    writeFileSync(join(dir, 'config', 'profiles.json'), JSON.stringify({ profiles: { 'twilio.sms': { provider: 'twilio', path } } }));
    const source = join(dir, 'source.env');
    writeFileSync(source, dotenv + 'UNRELATED_SECRET=never-copy\n', { mode: 0o600 });
    const run = (script, args, input) => spawnSync(process.execPath, [join(dir, 'scripts', script), ...args], {
      input, encoding: 'utf8', cwd: tmpdir(), env: { ...process.env, TWILIO_TO_NUMBER: 'invalid', TWILIO_AUTH_TOKEN: 'wrong' },
    });
    const imported = run('import-sms-profile.mjs', [source]);
    assert.equal(imported.status, 0, imported.stderr);
    assert.equal(run('import-sms-profile.mjs', [source]).status, 1);
    assert.equal(run('send-sms.mjs', ['--check']).status, 0);
    const dry = run('send-sms.mjs', ['--dry-run'], 'Hello $(literal)');
    assert.equal(dry.status, 0, dry.stderr);
    assert.equal(JSON.parse(dry.stdout).network, false);
    const file = join(dir, 'message.txt');
    writeFileSync(file, 'from file');
    assert.equal(run('send-sms.mjs', ['--dry-run', '--file', file]).status, 0);
    const bad = run('send-sms.mjs', ['--message', 'secret-input']);
    assert.equal(bad.status, 1);
    assert.ok(!bad.stderr.includes('secret-input'));
    const empty = run('send-sms.mjs', [], ' \n');
    assert.equal(JSON.parse(empty.stderr).code, 'empty_message');
    for (const value of [env.TWILIO_AUTH_TOKEN, env.TWILIO_TO_NUMBER, 'Hello $(literal)', 'never-copy']) {
      assert.ok(!(imported.stdout + dry.stdout + empty.stderr).includes(value));
    }
    assert.ok(!loadSmsConfig(path).password.includes('wrong'));
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
