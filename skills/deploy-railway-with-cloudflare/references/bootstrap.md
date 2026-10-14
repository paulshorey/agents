# Bootstrap and recovery

Examples were checked with Railway CLI 5.62.1. Inspect unfamiliar schema with
`railway api describe`. Use returned IDs and keep credentials out of arguments/output.
The manifest helper validates existing infrastructure; it does not create paid resources.

## Workspace project creation

`railway init` returned Unauthorized with the WebArts workspace token while explicit
API creation succeeded. Inspect paginated project inventory first; after a lost
response, reconcile state before retrying creation.

```sh
(
  source "$HOME/.config/railway/webarts.env"
  unset RAILWAY_TOKEN
  railway api 'mutation($input:ProjectCreateInput!){projectCreate(input:$input){id name workspaceId environments{edges{node{id name}}}}}' \
    --var 'input={"name":"REQUESTED_NAME","workspaceId":"CONFIRMED_WORKSPACE_ID","defaultEnvironmentName":"production"}'
)
```

Create additional environments using current `EnvironmentCreateInput` and
`environmentCreate` schema. Create services through native CLI/API, and configure
repository/branch sources in the owning IaC file. Do not duplicate existing databases,
volumes, or secrets incidentally. Sealed secrets need provisioning per environment.

Branch mappings are deployment triggers, not `ServiceSource.branch`:

```graphql
query($id:String!) {
  project(id:$id) {
    id name workspaceId
    environments { edges { node {
      id name
      deploymentTriggers { edges { node { serviceId branch repository } } }
    } } }
  }
}
```

## Domains and DNS

The tested IaC version adopted custom domains but could not register them initially:

```sh
railway domain HOST --port PORT --project PROJECT_ID --environment ENV_ID --service SERVICE_ID --json
railway domain status HOST --project PROJECT_ID --environment ENV_ID --service SERVICE_ID --json
```

Include registrations in IaC, then read `dnsRecords` for routing and
`verification.dnsHost`/`verification.token` for TXT. Verification tokens are public
DNS data. Use the actual provider requirements, not another project's target.
Paul's route records use DNS-only CNAME and TTL Auto.

```sh
~/.agents/bin/agents-hosting doctor --manifest ~/.agents/config/hosting/paul.json
~/.agents/bin/agents-hosting plan --manifest ~/.agents/config/hosting/paul.json --plan-file ~/.agents/local/hosting/paul.plan.json
~/.agents/bin/agents-hosting apply --manifest ~/.agents/config/hosting/paul.json --plan-file ~/.agents/local/hosting/paul.plan.json
~/.agents/bin/agents-hosting verify --manifest ~/.agents/config/hosting/paul.json
```

## Defaults and binaries

Paul showed perpetual false/null drift for explicit `sleepApplication: false`.
Verify the actual live default, omit redundant declarations, and require a clean
plan. Do not remove meaningful settings to silence a diff. One persistent replica
is intentional for the in-memory contact limiter.

Paul pins SDK 3.15.0 and native CLI 5.62.1. Its npm CLI installer introduced vulnerable
`tar` dependencies; overriding `tar` broke its import. Preserve the native installation
and repository pins. CI downloads the official native release binary.

References:

- https://docs.railway.com/cli/api
- https://docs.railway.com/infrastructure-as-code
- https://developers.cloudflare.com/api/resources/dns/subresources/records/methods/edit/
- https://developers.cloudflare.com/cf/get-started/resources/
