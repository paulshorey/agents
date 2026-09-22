---
name: codex-cloud-environments
description: Configure, test, edit, or troubleshoot Codex Cloud repository environments through the Codex settings UI. Use for setup and maintenance scripts, runtime versions, variables or secrets, cache behavior, network access, environment setup failures, and new Node, monorepo, database, Android, or Capacitor workspaces.
---

# Codex Cloud environments

Build a cloud workspace from the repository's real development workflow, then test it in Codex. Treat the checked-in bootstrap and documentation as the source of truth; keep the Codex UI scripts small.

Use the Computer Use capability to inspect or change `https://chatgpt.com/codex/cloud/settings/environments` when the user asks you to configure the live environment. Select the exact browser/profile named by the user. If none is named, use the browser that already has the settings page open. Do not use browser automation outside Computer Use.

Before changing the UI:

1. Inspect the repository, its `AGENTS.md`, package manifests/lockfiles, existing cloud or CI scripts, and environment documentation. Look under the user's project root, commonly `~/git`. Resolve a mistyped local folder from Git remotes or repository names rather than creating a duplicate checkout.
2. Determine what the environment must support: install, lint/test/build, databases, generated clients, native toolchains, local servers, and external services. Identify the default branch because Codex creates the cache from that branch before checking out a task branch.
3. Prefer an idempotent, checked-in Linux bootstrap that terminates successfully. Add or repair it when absent. It should detect existing tools, pin important versions, use the repository lockfile, avoid logging credentials, and provide a read-only or bounded verification command. Document it for humans and agents.
4. Run syntax checks and the smallest meaningful local validation. Commit and push the bootstrap to the branch the cloud environment clones before testing the environment.

Read [design and troubleshooting](references/design-and-troubleshooting.md) when authoring a bootstrap, selecting variable/secret placement, supporting a database or native toolchain, or diagnosing a failed setup. Read [UI procedure](references/ui-procedure.md) before creating or editing a live environment.

## UI scripts

The setup script runs once for a fresh cache with network access. It may install tools and dependencies, initialize a disposable local database, compile code, and clone the user's shared skills repository into `$HOME/.agents`. It must finish; never leave a foreground development server, watcher, emulator, or log tail running.

The maintenance script runs after Codex checks out the requested branch in a resumed cache. Keep it idempotent and cheaper than full setup. Refresh the shared skills checkout, reconcile dependencies or generated files affected by the new branch, restore or check local services, and exit. Use the repository's maintenance mode when it has one.

Both scripts must discover the checkout instead of assuming the initial directory. Codex setup can begin in `/workspace` while the repository is `/workspace/<name>`. A portable pattern is:

```bash
set -euo pipefail

agents_dir="$HOME/.agents"
agents_url="https://github.com/paulshorey/agents.git"
if [ -d "$agents_dir/.git" ]; then
  git -C "$agents_dir" fetch --prune origin
  git -C "$agents_dir" checkout main
  git -C "$agents_dir" reset --hard origin/main
elif [ -e "$agents_dir" ]; then
  echo "$agents_dir exists but is not the expected Git checkout" >&2
  exit 1
else
  git clone --depth 1 "$agents_url" "$agents_dir"
fi

repo_root=""
for candidate in /workspace/* "$PWD"; do
  if [ -d "$candidate/.git" ] && [ -f "$candidate/EXPECTED_FILE" ]; then
    repo_root="$candidate"
    break
  fi
done
[ -n "$repo_root" ] || { echo "Repository checkout not found" >&2; exit 1; }
cd "$repo_root"
```

Replace `EXPECTED_FILE` with a repository-specific marker and invoke the checked-in bootstrap. Do not use an unbounded search across the filesystem. If the shared skills repository is private, use an authenticated URL mechanism already provided by the environment and never embed a token in the script.

## Environment data

Use normal environment variables for values the agent or programs must read after setup. Codex secrets exist only during setup; use them for install-time credentials. If a project explicitly requires a setup-only secret later, its bootstrap may persist only the necessary value in a user-owned file with mode `600`, source that file from the agent's shell, and ensure it never enters the repository or logs. Prefer a normal environment variable when the value is intentionally needed throughout the task.

Do not reveal, echo, or copy secret values into source files, commits, task prompts, or reports. Confirm the destination and variable names before entering sensitive values in the UI. Preserve existing values when editing an environment unless the user asked to replace them.

### GitHub authentication for pushes and pull requests

`GH_TOKEN` is an environment-variable name understood by GitHub CLI; it is not
a separate token type. Its value can be a GitHub fine-grained personal access
token, whose current prefix is `github_pat_`, or another token accepted by
GitHub. `GH_TOKEN` takes precedence over `GITHUB_TOKEN` for `github.com`.

When agents must push branches or create pull requests after setup:

1. Use a fine-grained PAT restricted to the intended resource owner and the
   smallest repository set. Grant repository **Contents: read and write** and
   **Pull requests: read and write**; Metadata read access is included. Add
   **Workflows: read and write** only when agents must push changes under
   `.github/workflows/`.
2. Put the PAT value in the Codex environment's normal variable named
   `GH_TOKEN`. Do not put it in a setup-only Secret, because the agent phase
   needs it. Do not create a second token merely because the local variable is
   named `GITHUB_PAT`; variable names and token types are independent.
3. Enable task-time network access to `github.com` and `api.github.com`, with
   the HTTP methods required for Git smart HTTP and the GitHub API. Prefer an
   allowlist when the UI supports it.
4. Configure HTTPS Git credentials without storing the token itself:

   ```bash
   if [ -n "${GH_TOKEN:-}" ] && command -v gh >/dev/null 2>&1; then
     gh auth setup-git
     gh api user --jq .login >/dev/null
   fi
   ```

   Run this in setup and maintenance, or immediately before GitHub work. It
   configures Git to ask `gh` for credentials; it does not write the PAT into a
   repository remote URL. Confirm that the remote uses HTTPS when relying on
   this flow.
5. Verify only non-secret facts: `gh api user --jq .login`, repository access,
   and a dry read such as `gh repo view OWNER/REPO`. Never run `gh auth token`,
   echo the variable, enable shell tracing, or place the token in a command-line
   URL. Treat task-time variables as exposed to agent-generated programs, so use
   expiration and least privilege and rotate a token after suspected exposure.

## Test and finish

Use the environment's test function after every material change. Inspect the complete setup or maintenance output, not only the exit code. If a test fails, fix the smallest responsible layer, save, and rerun; stop after repeated failure with the same external cause and report the exact stage and useful non-secret log excerpt.

After setup passes, connect an interactive terminal when available and verify the repository marker, shared skill discovery, tool versions, and the project's bounded health/build/test command. Reset the cache when repository changes make cached tool or dependency state incompatible. Record the final setup/maintenance scripts and required variable names in repository documentation so a human can reproduce the environment.

Do not treat a successful dependency install as proof the workspace is ready. The final check must exercise the project's real critical path: for example a build and health endpoint, a local database migration plus tests, or an Android Kotlin compile.
