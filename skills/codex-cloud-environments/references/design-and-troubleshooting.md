# Design and troubleshooting

Use this reference when writing or repairing repository bootstraps for Codex Cloud.

## Lifecycle facts

- A fresh environment checks out the repository's default branch, runs setup in a separate Bash session, and caches the resulting container for up to about 12 hours.
- A resumed cache checks out the task branch and then runs maintenance. Maintenance must account for dependency and generated-file changes between the cached default-branch commit and the task branch.
- Editing setup, maintenance, variables, or secrets invalidates the cache automatically. Reset it manually when a repository change invalidates cached state without changing those fields.
- Setup has network access. Agent-phase network access is separately configured and is off by default. Outbound traffic runs through an HTTP/HTTPS proxy, so installers that assume direct GitHub release access may fail.
- Do not assume that "unrestricted" agent internet makes arbitrary outbound TCP available. A PostgreSQL/MySQL connection can still fail because the cloud environment's egress path is an HTTP/HTTPS proxy. Test the actual protocol from the environment; use an isolated local database when direct database TCP is unavailable.
- `export` in setup does not persist into the agent shell. Use an environment setting, a shell startup file, or a generated project env file as appropriate.
- User skills belong in `$HOME/.agents/skills`; repository-specific skills belong in `<repo>/.agents/skills`. A checkout at `<repo>/.codex` is not a skill discovery location.

## Bootstrap qualities

A useful checked-in bootstrap:

- supports Debian/Ubuntu Linux and does not assume macOS, `/workspace/<hardcoded-name>`, `sudo`, or a preselected shell;
- is safe to rerun and separates durable installation from per-boot reconciliation;
- pins runtime/package-manager/toolchain versions or derives them from checked-in version files;
- installs with the lockfile (`pnpm install --frozen-lockfile`, `npm ci`, Gradle wrapper);
- validates required inputs by name while never printing their values;
- avoids `set -x`, credential-bearing URLs in output, and committed `.env` files;
- refuses destructive database seeds/resets against shared hosts unless that behavior is the explicit project contract;
- has `--help` plus bounded modes such as `check`, `verify`, `build`, or `maintenance`;
- exits after setup. Starting servers belongs in a separate command unless the cloud product explicitly provides a supervised start hook.

Prefer runtimes already installed in the universal image when they satisfy the
project's pinned version. Search managed locations such as mise before using
`apt`; an inherited `JAVA_HOME` can point at a newer default even when the
required JDK is already present.

Keep long package installations observable without flooding the browser
terminal. Capture verbose `apt`/`dpkg` output to a temporary log, use
`Dpkg::Use-Pty=0`, print a short progress line every 15–30 seconds, and emit the
captured log only on failure. A completely silent multi-minute command and a
multi-thousand-line license or package transcript can both make the interactive
tester look stuck.

## Project patterns

### Node, Vite, Next.js, API, or monorepo

Use the repository's pinned Node and package-manager versions. Install all workspace dependencies once. Build or typecheck the packages necessary for an agent to begin work. In maintenance, rerun the frozen install; package managers normally make an unchanged install cheap. Run code generation when schema or generator inputs may differ by branch.

Do not start a web server in setup or maintenance. Offer a separate checked-in start command and a health endpoint. Avoid ports reserved by browsers or platform services; if a chosen port fails, fix the repository script rather than hiding the failure only in the UI.

### Local disposable database

Install the matching client/server extensions, start the service without assuming `sudo`, create development and test databases idempotently, and apply only forward migrations. Generate credentials locally for throwaway databases. Keep database files in the container cache and make maintenance restart the service and apply newly checked-in migrations.

### Shared or hosted database

Put the connection URL in a normal environment variable if agents need it after setup. Start with a read-only connectivity probe. Migration behavior must follow repository policy; do not infer authorization from mere access. Never run reset or seed against a shared host unless explicitly designed and authorized. If setup persists a setup-only credential for later use, use a user config directory, mode `600`, exact key allowlisting, and shell startup sourcing without output.

Test the database protocol before making a hosted database part of setup. Codex
Cloud's documented egress proxy is for HTTP/HTTPS traffic; a provider's direct
PostgreSQL port may remain unreachable. In that case, provision a disposable
local database for cloud development, preserve the hosted URL without printing
it, and document that production-like database verification belongs on a host
with direct TCP access.

### GitHub pushes and pull requests

Codex's repository connection and checkout do not guarantee that arbitrary
shell commands can push or create pull requests during the agent phase. For
that workflow, make a least-privilege fine-grained PAT available as the normal
environment variable `GH_TOKEN`, enable task-time access to GitHub, and use
`gh auth setup-git` so HTTPS Git obtains credentials from GitHub CLI. A local
variable called `GITHUB_PAT` can hold the same PAT; copy its value into the
cloud variable named `GH_TOKEN` without printing it.

Do not put an agent-required PAT in a setup-only Secret. Do not persist it in a
repository `.env`, Git URL, credential file, or setup log. A GitHub App is the
better long-term choice when many repositories, multiple users, automatic
rotation, or centrally revocable installation permissions are required.

### Android

Use the Gradle wrapper. Install a supported JDK, Android command-line tools, exact platform/build-tools versions, and the project NDK when required. Write a portable env file for `JAVA_HOME`, `ANDROID_HOME`, and `ANDROID_SDK_ROOT`; source it in later shells. Warm Gradle with a Kotlin compile or narrow unit test. Build an APK only when useful because it increases setup time and cache size.

Accept required Android SDK licenses noninteractively. Redirect the license text
away from the web terminal: `sdkmanager --licenses` can print thousands of
lines and stall a cloud setup UI even while `yes` is supplying the answers.
Keep package download and compiler output visible so failures remain diagnosable.

Codex Cloud Linux can compile/test Android and create APK/AAB artifacts. `adb install` requires an attached device or emulator and normally cannot validate installation in a generic cloud workspace.

### Capacitor and iOS/Android

Build and test the web app and Android artifacts on Linux. Capacitor sync/generation can run where its dependencies support Linux. Native iOS compilation, signing, Simulator checks, and App Store archives require macOS/Xcode and should remain in a macOS CI or developer workflow. Document this boundary so a Cloud agent does not repeatedly try to install Xcode on Linux.

## Common failures

### Repository script is missing

Setup always sees the remote default branch used to create the cache, not unpushed local files or an unrelated feature branch. Commit and push the bootstrap, then reset or recreate the cache.

### `cd` fails or the manifest is missing

The script probably assumed it starts in the checkout. Inspect `/workspace` and locate the single Git checkout using a repository-specific marker. Change directory before package commands.

### A binary package fails in `postinstall`

First prefer a supported package-manager configuration. Behind the Codex proxy, some installers fail while ordinary `curl` succeeds. As a narrow fallback, install dependencies without scripts, rebuild only approved native packages, download the exact pinned release with checksum/version verification, place it in the package's expected location, and verify `--version`. Document this exception and revisit it when the upstream installer changes.

### Setup succeeds but the agent cannot see a variable

Setup runs in a separate shell. Move non-sensitive values to environment settings or shell startup. Secrets are intentionally removed before the agent phase; use a normal environment variable when the agent is meant to access the value.

### Cached task uses stale dependencies

Add a cheap lockfile-based install or repository maintenance mode to maintenance. Reset the cache after major toolchain changes.

### A command never completes

Look for a dev server, watcher, emulator, background log follower, interactive prompt, or authentication flow. Setup and maintenance must be noninteractive and terminate. Add noninteractive flags and time-bounded health checks.

## Authoritative references

- Codex Cloud environments: https://developers.openai.com/docs/environments/cloud-environment
- Agent internet access: https://developers.openai.com/docs/cloud/internet-access
- Codex skills and discovery locations: https://developers.openai.com/docs/build-skills
- GitHub CLI environment variables: https://cli.github.com/manual/gh_help_environment
- GitHub personal access tokens: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens
