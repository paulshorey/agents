# Local adaptations to pinned 3.28.0

The pinned upstream revision and licenses remain recorded in `licenses/README.md`
in the shared agent repository. Preserve these changes when updating the import.

Hosted API v1 accepts topic, depth and audience register. Explicit local retrieval
constraints (date/window, source filters, query plans, handles, limits and similar
options), HTML output, and configured default/excluded source filters are rejected
before a hosted search starts. The error names the unsupported options. Unset
`LAST30DAYS_API_KEY` or `LAST30DAYS_API_BASE` in the research command's environment
to run those requests with the local engine. This avoids silently broadening a
request or silently switching to other paid local providers.

`watchlist.py run-all` polls each topic's persisted five-field **UTC** cron schedule.
An external scheduler should invoke it once per minute; installation does not
create that scheduler. A missed minute is not replayed. Daily and `--weekly`
schedules use 08:00 UTC, with weekly topics due on Monday. Numeric fields support
wildcards, lists, ranges and positive steps; weekday 0 or 7 means Sunday.
Restricted day-of-month and weekday fields combine with OR, following cron.
Names, macros and extended cron syntax are rejected before saving. Existing invalid
schedules are skipped with a reason rather than researched at every poll.

A topic already attempted in the current scheduled minute is skipped, including
failed attempts; `run-one` remains the explicit immediate/manual retry command.
Use one scheduler process: this minute check is not a concurrent-run lock. Invalid
last-run timestamps fail closed. Budget skips do not consume a scheduled attempt.

Budget configuration rejects invalid, negative and nonfinite amounts before
persisting them. Post-subprocess report validation or storage failures set the run
to failed when run-status storage remains available, and the usage journal is
still finalized. Error summaries contain exception types rather than report data.

Run `python3 -m unittest discover -s tests -p test_last30days_review.py -v` from the
shared repository for offline regressions using temporary SQLite and mocked
provider/subprocess boundaries. No provider authentication or research is proven
by these tests.
