---
name: local-dev-services
description: Check, repair, start, or restart the local web services managed by ~/git/local-dev and their private Tailscale URLs, preserving current branches and uncommitted files. Use for local server availability and refreshing running code, not hosted deployments or ingestion/collection jobs.
---

# Local dev services

Read `~/git/local-dev/AGENTS.md` and `docs/managed-services.md` there first.
`config.json` owns the catalog, commands, ports, probes and publication settings;
never keep a second port list in this skill. Use the existing central managers.

## Choose the requested operation

- **Status:** run the bundled read-only checker. Report local health, ownership,
  Tailscale state, proxy state and actual HTTPS probe responses separately.
- **Ensure / repair:** start missing enabled services, restart an unhealthy owned
  service once, or restore a missing proxy. Preserve healthy services. Use the
  recovery procedure below; a check-only request does not authorize repair.
- **Restart all / refresh running code:** perform the full restart in the
  [operations reference](references/operations.md). This includes the controller
  and idle app-manager retirement, so current worker code and runtime load too.

```sh
node ~/.agents/skills/local-dev-services/scripts/status.mjs
node ~/.agents/skills/local-dev-services/scripts/status.mjs --json
# Print an existing compatible runtime; this does not install anything.
node ~/.agents/skills/local-dev-services/scripts/status.mjs --node
```

The checker exits 0 only when every enabled service has a verified healthy local
listener and any requested private route passes its HTTPS probe. Exit 1 identifies
unavailable or unverified services. It does not open dashboard Shells, run Git,
print environment values, change routes or restart anything.

## Repair Tailscale at the right layer

1. Inspect `tailscale status --json` and `tailscale serve status --json`.
   `Running` plus verified private requests needs no network restart. A phone
   being offline by itself is not a desktop service failure.
2. If the macOS app is absent/unresponsive, try `open -g -a Tailscale` once and
   recheck for up to 30 seconds. For an existing authenticated `Stopped` state,
   use bounded `tailscale up` without setting-changing flags; see the reference.
3. `NeedsLogin`, expired authentication, device approval or a still-unresponsive
   VPN requires human attention. Do not log out, switch accounts, force reauth,
   reset Serve, kill VPN/system daemons, or enable Funnel as automatic recovery.
   An explicit request to restart the native app permits one graceful quit/open
   cycle; recheck the existing connection afterward.
4. With networking restored, repair only affected routes using central
   `proxy`/`detach` actions. Local servers can stay healthy through route loss.
   The controller uses its dedicated start command. Verify HTTPS afterward.

## Source freshness and scheduling

Next/Vite and watch-mode commands normally pick up source edits. Plain Node and
Python servers may need a restart; inspect each configured command and its
package script. In this catalog the controller, Events, Trading API and Map
ingestion dashboard have no source watcher; verify the current scripts rather
than assuming that list stays current. Configuration, environment, dependency
and manager changes can also require a fresh start.

Health is not proof of current source freshness. If the user asks to load all
latest local files, use the full restart unless watcher/source evidence resolves
the request. For a future schedule, distinguish availability repair from source
freshness: explicitly include changed-source detection or a chosen restart
policy for services without watchers. Never create a schedule just by installing
or invoking this skill. Never pull, checkout, commit, stash, reset or clean repos.

Keep credentials/dotenv, migrations, business data, collectors and ingestion
workers out of service recovery. Preserve pinned devices, private guards and
upstream framing headers. Never kill unidentified listeners. Bound recovery to
one attempt per affected service/route, then report the unresolved cause.

Report repaired components, remaining failures and usable private links. Save
sanitized run evidence only in ignored local state. For scheduled runs, follow
the user's notification policy and remain quiet for unchanged healthy state.
