#!/usr/bin/env node
import { execFile } from 'node:child_process';
import { readdir } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { parseArgs, promisify } from 'node:util';
import { pathToFileURL } from 'node:url';

const execute = promisify(execFile);
export async function selectNode24(root, { current = process.execPath, preferred = process.env.LOCAL_DEV_NODE, run = execute, list = readdir } = {}) {
  const candidates = [preferred, current].filter(Boolean);
  const cache = path.join(root, '.state', 'runtime');
  const entries = await list(cache).catch((error) => { if (error.code === 'ENOENT') return []; throw error; });
  for (const entry of entries.filter((name) => /^node-v24\.\d+\.\d+-darwin-(arm64|x64)$/.test(name)).sort((a, b) => b.localeCompare(a, 'en', { numeric: true }))) {
    candidates.push(path.join(cache, entry, 'bin', 'node'));
  }
  for (const candidate of [...new Set(candidates)]) {
    try {
      const result = await run(candidate, ['--version'], { timeout: 5000 });
      if (/^v24\./.test(result.stdout.trim())) return candidate;
    } catch { /* Try another existing candidate; never install or upgrade. */ }
  }
  throw new Error('Node 24 is unavailable. Supply an existing LOCAL_DEV_NODE or resolve the runtime prerequisite.');
}

export async function probeHttps(url) {
  try {
    const result = await execute('curl', ['--silent', '--show-error', '--connect-timeout', '5', '--max-time', '20', '--output', '/dev/null', '--write-out', '%{http_code}', url], { timeout: 22000 });
    const status = Number(result.stdout.trim());
    return { ok: status >= 200 && status < 300, status };
  } catch { return { ok: false, status: null, error: 'Private HTTPS request failed; inspect DNS, TLS, network and route state.' }; }
}

export async function summarize(snapshot, request = probeHttps) {
  const hostname = snapshot.tailscale?.hostname;
  const privateHost = snapshot.tailscale?.running && typeof hostname === 'string' && /^[a-z0-9][a-z0-9.-]*\.ts\.net$/i.test(hostname);
  const pending = snapshot.apps.flatMap((app) => app.services.filter((s) => s.enabled !== false).map((service) => ({ app, service })));
  const services = [];
  let next = 0;
  async function work() {
    for (;;) {
      const item = pending[next++];
      if (!item) return;
      const { app, service: s } = item;
      const localHealthy = s.safe === true && s.health?.ok === true;
      const publicationRequested = s.publish !== false;
      const probePath = s.probe ?? '/';
      const url = privateHost && s.httpsPort ? 'https://' + hostname + ':' + s.httpsPort + probePath : null;
      const routeReady = s.proxyOwned === true && s.proxyState === 'ready';
      const https = publicationRequested && url && routeReady ? await request(url) : null;
      const ready = localHealthy && (!publicationRequested || (routeReady && https?.ok === true));
      services.push({
        app: app.id, service: s.name, port: s.port, status: s.status, owned: s.owned === true,
        localHealthy, publicationRequested, proxyState: s.proxyState, proxyOwned: s.proxyOwned === true,
        probeUrl: publicationRequested ? url : null, https, ready,
      });
    }
  }
  await Promise.all(Array.from({ length: Math.min(4, pending.length) }, work));
  services.sort((a, b) => a.port - b.port);
  return {
    checkedAt: new Date().toISOString(),
    tailscale: { running: snapshot.tailscale?.running === true, hostname: hostname ?? null },
    ready: services.length > 0 && services.every((s) => s.ready),
    sourceFreshness: 'Not checked; health does not establish source freshness.',
    services,
  };
}

export async function main(argv = process.argv.slice(2)) {
  const { values } = parseArgs({ args: argv, options: {
    root: { type: 'string', default: path.join(os.homedir(), 'git', 'local-dev') },
    json: { type: 'boolean' }, node: { type: 'boolean' }, help: { type: 'boolean' },
  } });
  const root = path.resolve(values.root);
  if (values.help) {
    console.log('Read-only local-dev status: status.mjs [--root PATH] [--json] | --node');
    return 0;
  }
  if (values.node) { console.log(await selectNode24(root)); return 0; }
  const { AppsManager } = await import(pathToFileURL(path.join(root, 'src', 'apps.js')).href);
  const manager = new AppsManager(path.join(root, 'config.json'));
  let report;
  try { report = await summarize(await manager.snapshot()); }
  finally { manager.dispose(); }
  if (values.json) console.log(JSON.stringify(report, null, 2));
  else {
    console.log('Tailscale: ' + (report.tailscale.running ? 'running' : 'unavailable') + (report.tailscale.hostname ? ' / ' + report.tailscale.hostname : ''));
    for (const s of report.services) {
      console.log((s.ready ? 'READY ' : 'FAIL  ') + s.app + '/' + s.service + ' :' + s.port + ' | local=' + s.localHealthy + ' owned=' + s.owned + ' proxy=' + s.proxyState + ' HTTPS=' + (s.https?.status ?? 'unverified') + (s.probeUrl ? ' | ' + s.probeUrl : ''));
    }
    console.log(report.services.filter((s) => s.ready).length + '/' + report.services.length + ' services ready. Source freshness is a separate check.');
  }
  return report.ready ? 0 : 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().then((code) => { process.exitCode = code; }).catch((error) => {
    console.error(error.message?.startsWith('Node 24 is unavailable.') ? error.message : 'Status check failed. Verify the local-dev root, compatible runtime and installed manager APIs; no recovery was attempted.');
    process.exitCode = 1;
  });
}
