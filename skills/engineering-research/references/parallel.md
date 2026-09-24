# Parallel access: failures and advanced use

## Failures and retries

Preserve successful results and create a new input containing only failed requests. A single-request input is fine for targeted retries.

- **HTTP 429:** respect `retry_after` when returned (seconds or an HTTP date); otherwise use exponential backoff with jitter. Reduce batch size and retry at most twice. Keep progress updates during longer waits. Do not rotate plugin session identifiers to evade limits.
- **HTTP 401/403:** report the authentication/access failure; do not repeatedly retry the same credential. Continue through the skill's fallback order when useful.
- **Other errors:** retry only plausibly transient failures, at most twice. Do not repeatedly submit invalid input unchanged. Report any evidence gaps that remain.

## Optional CLI capabilities

Use `parallel-cli` only when explicitly requested or when a needed capability is missing from the helper. Check `command -v parallel-cli` and its relevant `--help`; installation is separate from this skill. The CLI accepts `PARALLEL_API_KEY` or an existing OAuth login.

For a suitable longer research job, `parallel-cli research run "question" --no-wait --json` returns a run identifier. Check status and poll that same run with bounded waits; never start another job just to check progress. Read the report and inspect its sources before relying on it.

## Official documentation

- [Search API](https://docs.parallel.ai/api-reference/search/search): API fields and response schema.
- [Search MCP](https://docs.parallel.ai/integrations/mcp/search-mcp): search/fetch tools and connection authentication.
- [CLI](https://docs.parallel.ai/integrations/cli): extraction and research commands.
- [Task MCP](https://docs.parallel.ai/integrations/mcp/task-mcp): separate authenticated research-job integration.
