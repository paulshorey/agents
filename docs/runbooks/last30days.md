# last30days configuration

The imported [`last30days`](../../skills/last30days/SKILL.md) skill keeps its
machine settings in `~/.config/last30days/.env` (inventory
`application.last30days-config`). The engine owns that file: it creates it with
mode 600 during first-run setup and writes consent markers and keys through its own
commands. Nothing in it belongs in Git, and this repository holds no backup of it.

Commands below use the installed skill and a Python 3.12+ interpreter:

```sh
SKILL_DIR="$HOME/.agents/skills/last30days"
LAST30DAYS_PYTHON="$(command -v python3.14 || command -v python3.13 || command -v python3.12)"
```

## Where settings come from

The engine resolves each setting from the first source that has it:

1. Process environment, including exports from `~/.secrets.sh` (for example
   `PARALLEL_API_KEY` and `PERPLEXITY_API_KEY`).
2. A project `.claude/last30days.env`, only when trust is granted by the process
   environment or the global file.
3. `~/.config/last30days/.env`.
4. macOS Keychain generic passwords named `last30days-<KEY>`.

Use `"$LAST30DAYS_PYTHON" "$SKILL_DIR/scripts/last30days.py" --diagnose` to see the
sources the engine will actually use. Inspect the file by key names only; never print
its lines.

## Update

- Add or rotate a source key without echoing it: pipe the value on stdin to
  `"$LAST30DAYS_PYTHON" "$SKILL_DIR/scripts/last30days.py" setup --store-key NAME`
  (allowlisted names such as `SCRAPECREATORS_API_KEY`, `XAI_API_KEY`, and
  `X_BEARER_TOKEN`), or store it in Keychain with
  `bash "$SKILL_DIR/scripts/setup-keychain.sh" NAME`, which prompts for the value.
- Opt in to paid sources by setting `INCLUDE_SOURCES` in the file, as described in
  the skill's [setup wizard](../../skills/last30days/references/setup-wizard.md).
  A ScrapeCreators key spends credits on Reddit and YouTube backfill; set
  `LAST30DAYS_REDDIT_SC_MIN_ITEMS=0` or `LAST30DAYS_YT_SC_MIN_ITEMS=0` to limit it.
- Install the optional Digg, arXiv, and Techmeme CLIs by installing Go
  (`brew install go`) and re-running `setup`.

## Revoke browser access

Paul granted browser-cookie consent on 2026-11-02 for X reads on later runs. To
revoke it, set `BROWSER_CONSENT=false` (or `FROM_BROWSER=off`) in the file, keeping
the other lines. A later consented `setup --allow-browser-cookies` replaces a saved
refusal, but `FROM_BROWSER=off` blocks reads until it is changed. Cookie values are
never stored; macOS privacy settings control which browsers the engine can read.

## Check and repair

```sh
"$LAST30DAYS_PYTHON" "$SKILL_DIR/scripts/last30days.py" doctor
"$LAST30DAYS_PYTHON" "$SKILL_DIR/scripts/last30days.py" doctor --postmortem
```

`doctor` reports each source as working, unverified, not working, or available;
`--postmortem` explains the last run's failures. Follow the setup wizard's repair
entry for X, Reddit, and YouTube fixes. A doctor result does not authorize installs,
browser reads, or configuration writes.

## Recover

If the file is lost or corrupted, move it aside and run the skill again: the
first-run gate reappears, and setup recreates the markers after asking for consent.
Keys stored only in the file must be reissued by their providers (ScrapeCreators,
xAI, or the X developer console); Keychain items survive. Run caches beside the file
(`last-run.json`, `last-report.json`, `doctor-cache.json`) are disposable, and saved
research under `~/Documents/Last30Days` is independent of the configuration.
