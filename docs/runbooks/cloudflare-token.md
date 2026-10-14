# Cloudflare token: locate, update, and recover

Start with `agents-config show cloudflare.dns-token`. The profile location comes
from `config/hosting/paul.json`; it currently resolves to
`~/.agents/local/credentials/cloudflare.env`. This ignored file supplies
`CLOUDFLARE_API_TOKEN` to the pinned CLI, hosting API, and Codex MCP header helper.
It also stores the non-secret `CLOUDFLARE_ACCOUNT_ID` selector. New projects select
their own zone in a manifest; the all-domains profile has no global zone default.
An inherited `CLOUDFLARE_ZONE_ID` can still supply a fallback when no explicit zone
ID is declared. Inspect or unset that selector when changing project context;
credential scope and command target selection are separate concerns.

## Change permissions

Open [Cloudflare user API tokens](https://dash.cloudflare.com/profile/api-tokens),
find **Agent DNS — all domains**, and inspect its summary. The registered scope is
DNS Edit and Zone Read for all zones, plus User Details Read for hosted MCP identity.
Editing permissions preserves the token value; rolling a token changes it.
Scope changes require authorization for the specific added access. The inventory
describes capability and does not authorize changes to unrelated zones.

After an authorized scope edit, update `config/inventory.json`, regenerate the
inventory, and record the reason and verification in `CHANGELOG.md`. If the token
value is unchanged, no local credential replacement is necessary.

## Replace the local token value

Obtain the replacement through Cloudflare's supported token workflow. Keep its
value out of chat, Git, command arguments, shell history, and screenshots.
In your own terminal, run:

```sh
python3 ~/.agents/scripts/set-cloudflare-token.py
~/.agents/bin/agents-config check --live --save-status
```

The existing setup script prompts invisibly, validates the configured project zone,
and atomically writes the profile with mode 600 in a mode-700 directory. Its initial
validation does not establish all-zone access or MCP authentication. The live check
separately checks token status, user identity, the selected account's zones and DNS
permissions, hosted MCP access, and the registered Railway project. Read individual
results: an unrelated Railway failure does not invalidate a successful Cloudflare check.

When the provider supports replacement without immediate revocation, verify the
replacement before revoking the old credential. Some rotations invalidate the old
value immediately. Record replacement dates and affected consumers in the changelog,
never the value, its fragments, or a hash of it. Start a new agent session if an
existing MCP client has cached authentication. CLI wrappers reread the profile.

## Change configuration or account selection

- Change the shared endpoint in `config/mcp.json`; run `scripts/install.py`, review
  its findings, and use `--apply` to back up and render the updated settings.
- Change a project's account/zone/profile reference in its hosting manifest, after
  checking live provider identities. Run the hosting doctor before applying DNS.
- Cursor has separate OAuth state; its URL-only configuration does not reuse the
  Codex header helper. Connect through Cursor's supported sign-in when needed.

Never run `scripts/mcp-headers.py` to inspect its output: that output contains the
authorization header intended only for the application's internal authentication pipe.

## Recover on another machine

Clone this repository and restore its tools and configuration using the README.
Restore the token from your encrypted backup/password manager, or create a replacement
at Cloudflare, then use the hidden-input setup script. Git restores references and
instructions, not the secret. No secret backup service is configured by this repository.

References: [token updates](https://developers.cloudflare.com/api/resources/user/subresources/tokens/methods/update/),
[token rotation](https://developers.cloudflare.com/api/resources/user/subresources/tokens/subresources/value/methods/update/),
[official MCP](https://github.com/cloudflare/mcp).
