# Production promotions

For repositories using `main` for development and `prod` for production, an
authorized promotion merges all current `main` into `prod` through a PR with head
`main`, base `prod`. Feature/conflict fixes land in `main` first. Preserve intentional
production differences and inspect production-only commits; narrow releases need
an explicit request. Follow the project's migration/release workflow, inspect
pending migrations even when code is synchronized, and verify the deployed commit,
application/database health, and retained data. An unmerged feature PR is not part
of the release. Report an already-current promotion only after relevant validation.
For other branch models, follow the project's release workflow.
