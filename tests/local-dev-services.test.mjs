import test from 'node:test';
import assert from 'node:assert/strict';
import { summarize, selectNode24 } from '../skills/local-dev-services/scripts/status.mjs';

function snapshot(overrides = {}) {
  const service = { name: 'web', port: 4100, httpsPort: 4100, probe: '/api/health', safe: true, status: 'running', owned: true, enabled: true, publish: true, proxyOwned: true, proxyState: 'ready', health: { ok: true }, ...overrides };
  return { tailscale: { running: true, hostname: 'mac.test.ts.net' }, apps: [{ id: 'fixture', services: [service] }] };
}
const ok = async () => ({ ok: true, status: 200 });

test('status requires verified local identity, route ownership and actual private HTTPS', async () => {
  const requested = [];
  const result = await summarize(snapshot(), async (url) => { requested.push(url); return ok(); });
  assert.equal(result.ready, true);
  assert.deepEqual(requested, ['https://mac.test.ts.net:4100/api/health']);
  assert.equal(result.services[0].owned, true);
  for (const overrides of [{ safe: false }, { health: { ok: false } }, { proxyOwned: false }, { proxyState: 'conflict' }]) {
    assert.equal((await summarize(snapshot(overrides), ok)).ready, false);
  }
  const denied = await summarize(snapshot(), async () => ({ ok: false, status: 403 }));
  assert.equal(denied.ready, false);
  assert.equal(denied.services[0].https.status, 403);
});

test('attached external servers remain external while verified private access can be healthy', async () => {
  const result = await summarize(snapshot({ status: 'external', owned: false }), ok);
  assert.equal(result.ready, true);
  assert.equal(result.services[0].owned, false);
  assert.equal(result.services[0].status, 'external');
});

test('disconnected or invalid private hostname never triggers a request or claims readiness', async () => {
  for (const tailscale of [{ running: false, hostname: null }, { running: true, hostname: 'unrelated.example' }]) {
    const data = snapshot(); data.tailscale = tailscale;
    let requested = false;
    const result = await summarize(data, async () => { requested = true; return ok(); });
    assert.equal(result.ready, false);
    assert.equal(requested, false);
    assert.equal(result.services[0].probeUrl, null);
  }
});

test('disabled services are excluded and local-only publication policy is preserved', async () => {
  const data = snapshot({ publish: false, httpsPort: undefined, proxyOwned: false, proxyState: 'off' });
  data.apps[0].services.push({ ...data.apps[0].services[0], name: 'disabled', port: 4101, enabled: false, health: { ok: false } });
  let requested = false;
  const result = await summarize(data, async () => { requested = true; return ok(); });
  assert.equal(result.ready, true);
  assert.equal(result.services.length, 1);
  assert.equal(requested, false);
  assert.equal((await summarize({ tailscale: {}, apps: [] }, ok)).ready, false);
});

test('status never includes command environments, IPC tokens, or raw snapshot errors', async () => {
  const data = snapshot({ command: ['env', 'FIXTURE_SECRET=do-not-export'], error: 'do-not-export', runId: 'private-ipc-token' });
  const report = JSON.stringify(await summarize(data, ok));
  assert(!report.includes('do-not-export'));
  assert(!report.includes('private-ipc-token'));
});

test('runtime selection reuses an existing Node 24 and never installs or accepts another major', async () => {
  const attempts = [];
  const run = async (file) => { attempts.push(file); return { stdout: file.includes('24.22.2') ? 'v24.22.2\n' : 'v26.9.0\n' }; };
  const selected = await selectNode24('/fixture', { preferred: '/older/node', current: '/current/node', list: async () => ['node-v24.9.0-darwin-arm64', 'node-v24.22.2-darwin-arm64', 'unrelated'], run });
  assert.equal(selected, '/fixture/.state/runtime/node-v24.22.2-darwin-arm64/bin/node');
  assert.deepEqual(attempts, ['/older/node', '/current/node', selected]);
  await assert.rejects(selectNode24('/fixture', { preferred: undefined, current: '/current/node', list: async () => [], run }), /Node 24 is unavailable/);
});
