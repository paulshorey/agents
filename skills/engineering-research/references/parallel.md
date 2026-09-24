# Parallel access

## Default: API helper

`scripts/search.py` uses Python's standard library to call `POST https://api.parallel.ai/v1/search`. It sends `PARALLEL_API_KEY` as the API credential. No CLI installation is required.

Create a scratch JSON file with distinct research angles:

```json
{
  "searches": [
    {"objective": "Find current official guidance for X with Y.", "search_queries": ["X Y official integration", "X Y API documentation"]},
    {"objective": "Evaluate alternatives and failure cases for X with Y.", "search_queries": ["X Y integration alternatives", "X Y production pitfalls"]}
  ]
}
```

Run the helper from this skill's directory, replacing the input path:

```bash
if [ -z "${PARALLEL_API_KEY:-}" ] && [ -f ~/.secrets.sh ]; then
  source ~/.secrets.sh
fi
python3 scripts/search.py /absolute/path/to/searches.json
```

Check only whether the key is present; never print it, put it in the input file, or pass its value as a command argument. On another machine or in the cloud, use that environment's secret configuration; the local secrets file may not exist there.

Submit each batch once. The helper runs at most four requests concurrently, waits for completion, and returns indexed results and errors. A nonzero exit can coexist with useful successful results. A single-request input is allowed for narrow lookups or targeted retries.

## Failures and retries

The helper does not retry automatically. Preserve successful results and create a new input containing only failed requests.

- **HTTP 429:** respect `retry_after` when returned (seconds or an HTTP date); otherwise use exponential backoff with jitter. Reduce batch size and retry at most twice. Keep progress updates during longer waits. Do not rotate plugin session identifiers to evade limits.
- **HTTP 401/403:** report the authentication/access failure; do not repeatedly retry the same credential. Continue through the skill's fallback order when useful.
- **Other errors:** retry only plausibly transient failures, at most twice. Do not repeatedly submit invalid input unchanged. Report any evidence gaps that remain.

## Fallback: connected tools

Discover the available Parallel search and page-fetch tools directly; a plugin need not install a named skill. These tools use their own connection authentication, independently of shell variables. Keep one session identifier across related calls. Use small concurrent batches because anonymous access has lower limits.

## Optional CLI capabilities

Use `parallel-cli` only when explicitly requested or when a needed capability is missing from the helper. Check `command -v parallel-cli` and its relevant `--help`; installation is separate from this skill. The CLI accepts `PARALLEL_API_KEY` or an existing OAuth login.

For a suitable longer research job, `parallel-cli research run "question" --no-wait --json` returns a run identifier. Check status and poll that same run with bounded waits; never start another job just to check progress. Read the report and inspect its sources before relying on it.

## Official documentation

- [Search API](https://docs.parallel.ai/api-reference/search/search): API fields and response schema.
- [Search MCP](https://docs.parallel.ai/integrations/mcp/search-mcp): search/fetch tools and connection authentication.
- [CLI](https://docs.parallel.ai/integrations/cli): extraction and research commands.
- [Task MCP](https://docs.parallel.ai/integrations/mcp/task-mcp): separate authenticated research-job integration.
