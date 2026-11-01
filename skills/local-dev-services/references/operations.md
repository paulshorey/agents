# Operations for the existing local-dev managers

Use only for an authorized repair/restart. Check-only requests use `status.mjs`.
The owning repository remains authoritative; this reference adds no supervisor.
Run manager commands from `~/git/local-dev`, without Git or browser Shells.

## Prepare the runtime and inspect

```sh
LOCAL_DEV_NODE=$(node ~/.agents/skills/local-dev-services/scripts/status.mjs --node)
export PATH="$(dirname "$LOCAL_DEV_NODE"):$PATH"
cd ~/git/local-dev
tailscale status --json
tailscale serve status --json
node ~/.agents/skills/local-dev-services/scripts/status.mjs --json
```

Check `--node` succeeded before changing PATH. It accepts an existing Node 24
from PATH, `LOCAL_DEV_NODE`, or the owning repository's ignored `.state/runtime/`
cache. Missing runtime/dependencies are prerequisites to resolve within the
user's authorization, not permission for incidental global upgrades.

Recover an unavailable Tailscale connection before stopping services whose
existing proxies need cleanup; otherwise report cleanup as blocked.

Capture sanitized PID/CWD/manager/route identities under ignored `.state/` before
interrupting anything. Service `state.json` contains private IPC tokens: do not
dump whole state into chat or shared reports. App startup uses the invoking
environment; restart reuses in-memory service launch context. Preserve project
dotenv loading and never serialize shell exports into reports.

## Repair an affected app or service

```sh
"$LOCAL_DEV_NODE" tailscale-dev/apps-cli.mjs \
  --config="$PWD/config.json" --app=APP --service=SERVICE --action=start
```

Choose `restart` for an unhealthy **owned** service and `proxy` for a healthy
verified backend missing its route. If a stale owned route prevents repair, use
`detach` then `proxy` once. Start observes existing listeners without adopting
them. For a healthy external project server, Attach can publish it while keeping
it unowned when publication is requested; do not silently take control.
Unknown listeners/routes remain conflicts. Do not loop on a broken dependency.
If startup, manager recovery or another lifecycle action is already pending,
wait/recheck or rejoin it once through the existing locks; do not race it with
another restart or kill a manager to bypass the lock.

For the protected controller, use `node scripts/tailscale-dev.mjs start` to start
or restore its route; stop/start through that script if its server needs restart.
`pnpm dev:tailscale:status` reports the controller, not the entire workspace.

## Full restart

1. Stop all owned app services, then stop the controller. These commands use
   ownership checks and clean only their own private routes:

   ```sh
   "$LOCAL_DEV_NODE" tailscale-dev/apps-cli.mjs --config="$PWD/config.json" --all --action=stop
   "$LOCAL_DEV_NODE" scripts/tailscale-dev.mjs stop
   ```

2. Retire stopped app managers to load current manager code/runtime. Only use the
   existing verified idle-manager API, with its lifecycle locks:

   ```sh
   "$LOCAL_DEV_NODE" --input-type=module <<'JS'
   import { readCatalog } from './src/app-config.js';
   import { retireWorker, withAppLock } from './tailscale-dev/lib/app-runtime.mjs';
   const { apps } = await readCatalog('config.json');
   for (const app of apps.filter(a => !a.controller)) {
     await withAppLock(app.id, () => retireWorker(app.id));
   }
   JS
   ```

   If cleanup is pending, restore Tailscale and retry that component once. Never
   bypass ownership or kill a guardian while its route could still forward.

3. Check configured ports and any known old ports documented by the repository.
   Verify remaining listener PID, CWD and parent/watch process before stopping.
   For an explicitly requested full restart, stop matching external web-service
   parents before using the user's `killport PORT` helper on leftover listeners.
   It is not a blanket cleanup command. Never stop ingestion/collection workers,
   databases, unrelated listeners or original fallback profiles automatically.

4. Start the controller, then apps. Continue through individual failures:

   ```sh
   "$LOCAL_DEV_NODE" scripts/tailscale-dev.mjs start
   "$LOCAL_DEV_NODE" tailscale-dev/apps-cli.mjs --config="$PWD/config.json" --all --action=start
   node ~/.agents/skills/local-dev-services/scripts/status.mjs
   ```

   An app failure may skip later services in that app. Attempt those individually
   with `--service=...`, using the current catalog. At most one startup retry per
   failed service. Report database/schema/dependency failures; do not migrate,
   seed, rewrite credentials or relax health checks to claim success.

5. Verify every enabled backend and private route, then the actual HTTPS probes.
   Reloading the dashboard is a user action that also triggers configured pulls;
   do not load it as a restart/status fixture. Explain if a browser reload is
   needed for a changed preview-port frame policy.

## Native Tailscale connection recovery

On this Mac the desktop app owns the VPN. Do not install/start a competing
`tailscaled` service. Open an absent/unresponsive app with `open -g -a Tailscale`
and poll bounded status checks. If the existing authenticated connection is
`Stopped`, run `tailscale up` with an external 20-second command timeout and no
preference flags; it reconnects without changing settings. Check installed
`tailscale up --help` before relying on version-specific flags. Never add
`--reset`, `--force-reauth`, an auth key or new account settings as recovery.

For an explicit native-app restart, gracefully quit only the identified
Tailscale desktop app, open it once, and verify the existing account/backend and
the managers' private routes. If it needs login or OS approval, report that exact
human step. Do not repeatedly toggle a healthy VPN because one web app failed.

Official references: [CLI](https://tailscale.com/docs/reference/tailscale-cli),
[up](https://tailscale.com/docs/reference/tailscale-cli/up),
[macOS variants](https://tailscale.com/docs/concepts/macos-variants).
