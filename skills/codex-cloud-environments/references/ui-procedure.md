# Live Codex environment UI procedure

Use this only when the user asked to create or change the live Codex Cloud environment.

1. Open the Codex environments settings page with Computer Use in the requested browser/profile.
2. For an existing repository, open its row and record the current setup, maintenance, runtime, variables, secrets, network policy, and cache state. Keep unknown existing values intact.
   Read masked names from the detail page. After opening Edit, do not capture or
   print a full DOM/accessibility snapshot when value inputs may contain
   credentials; inspect only the specific controls or status text needed.
3. For a new environment, select the exact GitHub repository. Use a clear repository-based name if the UI asks for one.
4. Choose manual setup when the project has a checked-in bootstrap or needs services/native tools. Use the repository's runtime version where the UI can pin it; let the bootstrap own versions the UI cannot express.
5. Enter a small setup wrapper that:
   - updates or clones the shared skills repository at `$HOME/.agents`;
   - finds and enters the checked-out repository;
   - invokes the checked-in setup command;
   - exits after verification.
6. Enter a small maintenance wrapper that refreshes shared skills, enters the checkout, and invokes the repository's cheap maintenance/reconciliation command. It must not start a foreground server.
7. Add ordinary variables needed throughout an agent task. Add setup-only credentials as secrets. Do not move an agent-required database URL into Secrets because it will disappear before the agent phase.
   If approved values exist only in protected local files, do not weaken browser
   security or echo them into tool output to automate entry. Configure everything
   else and leave the exact named fields for secure manual entry.
8. Set agent network access to the smallest allowlist needed for task-time operations. Setup already has installation network access. Hosted databases or provider APIs used during tests require agent-phase access to their hosts.
9. Save and run the environment test. Follow the live log until success or a concrete error appears. Correct the script/configuration and rerun.
10. If available, connect a terminal and run a short post-setup check from the actual checkout. Verify `$HOME/.agents/skills`, the project toolchain, and one critical build/test/health path.
11. Leave repository documentation with the exact checked-in commands and variable names. Report configured settings and any capability intentionally left to another host, such as iOS/Xcode builds.

When the UI masks a value, treat it as present unless evidence shows it is wrong. Do not delete and recreate secrets merely to make the form look complete.
