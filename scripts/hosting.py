#!/usr/bin/env python3
"""Check Railway targets, reconcile Cloudflare DNS, and verify HTTPS deployments."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
UUID = re.compile(r'^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$')
PROJECT_QUERY = '''query($id:String!){project(id:$id){id name workspaceId
 environments{edges{node{id name deploymentTriggers{edges{node{serviceId branch repository}}}}}}}}'''


class HostingError(Exception):
    pass


def profile_environment(path, base=None):
    """Parse trusted owner-only dotenv data; never execute a shell profile."""
    env = dict(os.environ if base is None else base)
    file = Path(path).expanduser()
    if not file.exists():
        return env
    info = file.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise HostingError(f'Credential profile must be owned by you and mode 600: {file}')
    for line in file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'(?:export\s+)?([A-Z][A-Z0-9_]*)=(.*)', line)
        if not match:
            raise HostingError(f'Use literal dotenv assignments in {file}; shell commands are unsupported')
        values = shlex.split(match[2], comments=True)
        if len(values) > 1 or any(x in match[2] for x in ('`', '$(', '${')):
            raise HostingError(f'Use literal values in credential profile: {file}')
        env[match[1]] = values[0] if values else ''
    return env


def redact(text, env):
    for name, value in env.items():
        if value and len(value) > 8 and any(word in name for word in ('TOKEN', 'SECRET', 'PASSWORD', 'API_KEY')):
            text = text.replace(value, '<redacted>')
    return text


def run_json(command, env, cwd=None):
    try:
        result = subprocess.run(command, env=env, cwd=cwd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise HostingError(f'{command[0]} could not complete: {type(error).__name__}') from error
    if result.returncode:
        raise HostingError(redact(result.stderr or result.stdout, env).strip()[:1000])
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise HostingError(f'{command[0]} returned invalid JSON') from error
    if isinstance(data, dict) and data.get('errors'):
        raise HostingError(redact(json.dumps(data['errors']), env))
    return data


def load_manifest(path):
    data = json.loads(Path(path).expanduser().read_text())
    if data.get('schema_version') != 1:
        raise HostingError('Unsupported manifest schema_version')
    r, c, environments = data['railway'], data['cloudflare'], data['environments']
    for key in ('project_id', 'workspace_id', 'service_id'):
        if not UUID.fullmatch(r[key]):
            raise HostingError(f'Provide a real Railway {key} before running the helper')
    if not environments or not 1 <= r['port'] <= 65535:
        raise HostingError('Invalid environments or Railway port')
    zone = c['zone_name'].lower().rstrip('.')
    if not re.fullmatch(r'[a-z0-9.-]+\.[a-z]{2,}', zone):
        raise HostingError('Invalid zone_name')
    seen = set()
    for name, environment in environments.items():
        domain = environment['domain'].lower().rstrip('.')
        if not UUID.fullmatch(environment['id']) or not environment['branch']:
            raise HostingError(f'Provide an environment ID and branch for {name}')
        if (domain != zone and not domain.endswith('.' + zone)) or domain in seen:
            raise HostingError(f'Domain is outside the zone or duplicated: {domain}')
        if not environment.get('health_path', '/').startswith('/'):
            raise HostingError('health_path must begin with /')
        environment['domain'] = domain
        seen.add(domain)
    c['zone_name'] = zone
    return data


def railway_env(manifest):
    # Explicit profile wins over unrelated inherited workspace/project tokens.
    env = dict(os.environ)
    env.pop('RAILWAY_TOKEN', None)
    env.pop('RAILWAY_API_TOKEN', None)
    env = profile_environment(manifest['railway']['profile'], env)
    if not env.get('RAILWAY_API_TOKEN'):
        raise HostingError('Missing Railway workspace credential in the manifest profile')
    return env


def railway_project(manifest, env):
    data = run_json(['railway', 'api', PROJECT_QUERY, '--variables', json.dumps({'id': manifest['railway']['project_id']})], env)
    project = data.get('data', data).get('project')
    if not project or project['id'] != manifest['railway']['project_id'] or project['workspaceId'] != manifest['railway']['workspace_id']:
        raise HostingError('Railway project/workspace identity does not match the manifest')
    if project['name'] != manifest['name']:
        raise HostingError('Railway project name differs from the manifest; inspect the target')
    by_id = {edge['node']['id']: edge['node'] for edge in project['environments']['edges']}
    for name, wanted in manifest['environments'].items():
        actual = by_id.get(wanted['id'])
        if not actual or actual['name'] != name:
            raise HostingError(f'Railway environment identity mismatch: {name}')
        triggers = [edge['node'] for edge in actual['deploymentTriggers']['edges'] if edge['node']['serviceId'] == manifest['railway']['service_id']]
        if len(triggers) != 1 or triggers[0]['branch'] != wanted['branch'] or triggers[0]['repository'] != manifest['repository']:
            raise HostingError(f'GitHub repository/branch trigger mismatch: {name}')
    return project


def domain_status(manifest, name, env):
    target, r = manifest['environments'][name], manifest['railway']
    data = run_json(['railway', 'domain', 'status', target['domain'], '--project', r['project_id'], '--environment', target['id'], '--service', r['service_id'], '--json'], env)
    domain = data['domain']
    if domain['domain'] != target['domain'] or domain['targetPort'] != r['port']:
        raise HostingError(f'Domain identity or target port mismatch: {name}')
    return domain


class Cloudflare:
    """Stable REST fallback; credentials are kept out of subprocess arguments."""
    def __init__(self, manifest, environment=None):
        self.env = profile_environment(manifest['cloudflare']['profile'], environment)
        self.token = self.env.get('CLOUDFLARE_API_TOKEN')
        if not self.token:
            raise HostingError('Missing CLOUDFLARE_API_TOKEN; configure the owner-only profile documented in ~/.agents/README.md')
        self.zone_name = manifest['cloudflare']['zone_name']
        self.zone_id = manifest['cloudflare'].get('zone_id') or self.env.get('CLOUDFLARE_ZONE_ID')
        self.account_id = manifest['cloudflare'].get('account_id') or self.env.get('CLOUDFLARE_ACCOUNT_ID')

    def request(self, method, path, body=None):
        raw = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request('https://api.cloudflare.com/client/v4' + path, data=raw, method=method,
            headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json', 'User-Agent': 'paul-agents-hosting/1'})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    data = json.load(response)
                if not data.get('success'):
                    codes = [error.get('code') for error in data.get('errors', [])]
                    raise HostingError(f'Cloudflare API failed: error codes {codes}')
                return data
            except urllib.error.HTTPError as error:
                # Retry reads only. After a write timeout, resume with a new plan/read.
                if method == 'GET' and error.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(1 + attempt)
                    continue
                raise HostingError(f'Cloudflare HTTP {error.code} for {method} {path.split("?")[0]}') from error
            except (urllib.error.URLError, TimeoutError) as error:
                raise HostingError('Cloudflare request failed; inspect current state before retrying a write') from error
        raise HostingError('Cloudflare read retry limit reached')

    def zone(self):
        if self.zone_id:
            zones = [self.request('GET', '/zones/' + self.zone_id)['result']]
        else:
            query = {'name': self.zone_name, 'per_page': 50}
            if self.account_id:
                query['account.id'] = self.account_id
            zones = self.request('GET', '/zones?' + urllib.parse.urlencode(query))['result']
        if len(zones) != 1 or zones[0]['name'] != self.zone_name:
            raise HostingError('Cloudflare zone identity is ambiguous or does not match')
        zone = zones[0]
        if self.account_id and zone['account']['id'] != self.account_id:
            raise HostingError('Cloudflare account identity mismatch')
        self.zone_id = zone['id']
        return {'id': zone['id'], 'name': zone['name'], 'account_id': zone['account']['id']}

    def records(self, name):
        records, page = [], 1
        while True:
            query = urllib.parse.urlencode({'name': name, 'page': page, 'per_page': 100})
            data = self.request('GET', f'/zones/{self.zone_id}/dns_records?{query}')
            records.extend(data['result'])
            if len(data['result']) < 100:
                return records
            page += 1
            if page > 100:
                raise HostingError('Unexpectedly large DNS result; inspect zone manually')

    def write(self, operation):
        path = f'/zones/{self.zone_id}/dns_records'
        if operation['action'] == 'update':
            path += '/' + operation['id']
        return self.request('PATCH' if operation['action'] == 'update' else 'POST', path, operation['desired'])['result']


def comparable(record):
    result = {key: record[key] for key in ('type', 'name', 'content')}
    if result['type'] == 'CNAME':
        result['content'] = result['content'].lower().rstrip('.')
        result['proxied'] = record.get('proxied', False)
    elif result['type'] == 'TXT':
        # Cloudflare can return one quoted presentation string for TXT data.
        content = result['content']
        if len(content) >= 2 and content.startswith('"') and content.endswith('"'):
            result['content'] = content[1:-1]
    result['name'] = result['name'].lower().rstrip('.')
    return result


def record_operation(wanted, existing):
    """Never delete unrelated records or guess between competing route records."""
    same = [record for record in existing if record['type'] == wanted['type']]
    conflicts = [record for record in existing if record['type'] in ('NS',) or
        (wanted['type'] == 'CNAME' and record['type'] in ('A', 'AAAA', 'CNAME'))]
    if wanted['type'] == 'CNAME':
        candidates = conflicts
        if len(candidates) > 1 or any(record['type'] == 'NS' for record in candidates):
            raise HostingError(f'Ambiguous/conflicting route records for {wanted["name"]}; no records changed')
    else:
        if any(record['type'] == 'NS' for record in existing):
            raise HostingError(f'NS conflicts with TXT for {wanted["name"]}')
        # Verification hosts belong to this exact Railway registration; preserve other TXT data.
        candidates = [record for record in same if comparable(record)['content'].startswith('railway-verify=')]
        if len(candidates) > 1:
            raise HostingError(f'Multiple Railway verification records for {wanted["name"]}')
    if not candidates:
        return {'action': 'create', 'desired': wanted}
    actual = candidates[0]
    if comparable(actual) == comparable(wanted):
        return {'action': 'noop', 'id': actual['id'], 'desired': wanted}
    return {'action': 'update', 'id': actual['id'], 'before': comparable(actual), 'desired': wanted}


def required_records(domain, zone):
    records = []
    for record in domain.get('dnsRecords', []):
        if record['recordType'] != 'DNS_RECORD_TYPE_CNAME':
            raise HostingError('Unrecognized Railway DNS record type; inspect current domain schema')
        records.append({'type': 'CNAME', 'name': record['fqdn'], 'content': record['requiredValue'], 'proxied': False, 'ttl': 1})
    verification = domain.get('verification')
    if verification and verification.get('token'):
        host = verification['dnsHost'].rstrip('.')
        if host != zone and not host.endswith('.' + zone):
            host += '.' + zone
        records.append({'type': 'TXT', 'name': host, 'content': verification['token'], 'ttl': 1})
    if not any(record['type'] == 'CNAME' for record in records):
        raise HostingError('Railway has no CNAME requirements; register the domain first')
    for record in records:
        if record['name'] != zone and not record['name'].endswith('.' + zone):
            raise HostingError('Railway DNS requirement is outside the configured Cloudflare zone')
    return records


def manifest_digest(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()


def dns_plan(manifest, names, cloudflare=None):
    env = railway_env(manifest)
    railway_project(manifest, env)
    client = cloudflare or Cloudflare(manifest)
    zone = client.zone()
    operations = []
    for name in names:
        domain = domain_status(manifest, name, env)
        for wanted in required_records(domain, zone['name']):
            operations.append({'environment': name, **record_operation(wanted, client.records(wanted['name']))})
    return {'schema_version': 1, 'manifest_sha256': manifest_digest(manifest), 'project_id': manifest['railway']['project_id'], 'zone': zone, 'environments': names, 'operations': operations}


def apply_plan(manifest, saved, names):
    if saved.get('manifest_sha256') != manifest_digest(manifest) or saved.get('environments') != names:
        raise HostingError('Saved plan does not match this manifest/environment selection')
    client = Cloudflare(manifest)
    fresh = dns_plan(manifest, names, client)
    if saved != fresh:
        raise HostingError('Live DNS/Railway state changed since planning. Generate and review a fresh plan.')
    journal = ROOT / 'local/hosting' / (manifest['railway']['project_id'] + '.json')
    events = json.loads(journal.read_text()).get('events', []) if journal.exists() else []
    changed = []
    for operation in fresh['operations']:
        if operation['action'] == 'noop':
            continue
        current_operation = record_operation(operation['desired'], client.records(operation['desired']['name']))
        if current_operation != {key: value for key, value in operation.items() if key != 'environment'}:
            raise HostingError('DNS changed during apply; regenerate the plan before continuing')
        result = client.write(operation)
        event = {'record_id': result['id'], 'name': result['name'], 'action': operation['action']}
        events.append(event)
        changed.append(event)
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text(json.dumps({'zone_id': fresh['zone']['id'], 'events': events}, indent=2) + '\n')
        journal.chmod(0o600)
        after = record_operation(operation['desired'], client.records(operation['desired']['name']))
        if after['action'] != 'noop':
            raise HostingError('DNS write did not reconcile the record; inspect before continuing')
    final = dns_plan(manifest, names, client)
    if any(operation['action'] != 'noop' for operation in final['operations']):
        raise HostingError('DNS verification found remaining changes')
    return {'status': 'applied', 'changed': changed, 'follow_up_plan': final}


def doctor(manifest):
    checks = {}
    for name in ('railway', 'node', 'gh'):
        checks[name] = shutil.which(name)
    checks['cf'] = str(ROOT / 'tools/node_modules/.bin/cf') if (ROOT / 'tools/node_modules/.bin/cf').exists() else None
    ready = all(checks.values())
    for provider in ('railway', 'cloudflare'):
        try:
            if provider == 'railway':
                project = railway_project(manifest, railway_env(manifest))
                checks['railway_access'] = {'project_id': project['id'], 'workspace_id': project['workspaceId'], 'branches_verified': True}
            else:
                checks['cloudflare_access'] = Cloudflare(manifest).zone()
        except HostingError as error:
            checks[provider + '_access'] = {'error': str(error)}
            ready = False
    return {'ready': ready, 'checks': checks}


def verify(manifest, names):
    env = railway_env(manifest)
    railway_project(manifest, env)
    results = []
    for name in names:
        target = manifest['environments'][name]
        domain = domain_status(manifest, name, env)
        cert_status = domain.get('certificate', {}).get('status')
        host = target['domain']
        url = 'https://' + host + target.get('health_path', '/')
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'paul-agents-hosting/1'})
            with urllib.request.urlopen(request, timeout=20) as response:
                status, body = response.status, response.read(1024 * 1024)
                if urllib.parse.urlsplit(response.url).hostname != host:
                    raise HostingError('Health endpoint redirected to another host')
            with socket.create_connection((host, 443), timeout=20) as connection:
                with ssl.create_default_context().wrap_socket(connection, server_hostname=host) as tls:
                    tls_version = tls.version()
            health = json.loads(body) if target.get('health_path', '').startswith('/api/') else {}
            repository = Path(manifest['repository_path']).expanduser()
            head = subprocess.run(['git', 'ls-remote', 'origin', 'refs/heads/' + target['branch']], cwd=repository, capture_output=True, text=True, timeout=30)
            expected = head.stdout.split()[0] if head.returncode == 0 and head.stdout.strip() else None
            actual = health.get('commitSha') or health.get('commit') or health.get('gitCommitSha')
            if isinstance(actual, dict):
                actual = actual.get('sha')
            # Explicit schema makes this reusable without guessing application JSON fields.
            commit_field = target.get('commit_field')
            if commit_field:
                actual = health.get(commit_field)
            passed = status == 200 and cert_status == 'CERTIFICATE_STATUS_TYPE_VALID'
            if target.get('require_commit', False):
                passed = passed and bool(expected) and actual == expected
            results.append({'environment': name, 'url': url, 'http_status': status, 'tls': tls_version, 'certificate': cert_status, 'expected_commit': expected, 'reported_commit': actual, 'passed': passed})
        except (HostingError, OSError, ValueError, subprocess.TimeoutExpired) as error:
            results.append({'environment': name, 'url': url, 'passed': False, 'error': type(error).__name__})
    return {'verified': all(result['passed'] for result in results), 'results': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('doctor', 'plan', 'apply', 'verify'))
    parser.add_argument('--manifest', default=str(ROOT / 'config/hosting/paul.json'))
    parser.add_argument('--environment', choices=('dev', 'production', 'all'), default='all')
    parser.add_argument('--plan-file', type=Path, help='Save a plan, or read the reviewed plan for apply')
    args = parser.parse_args()
    try:
        manifest = load_manifest(args.manifest)
        names = list(manifest['environments']) if args.environment == 'all' else [args.environment]
        if any(name not in manifest['environments'] for name in names):
            raise HostingError('Requested environment is not present in the manifest')
        if args.command == 'doctor':
            result = doctor(manifest)
        elif args.command == 'verify':
            result = verify(manifest, names)
        elif args.command == 'plan':
            result = dns_plan(manifest, names)
            if args.plan_file:
                args.plan_file.parent.mkdir(parents=True, exist_ok=True)
                args.plan_file.write_text(json.dumps(result, indent=2) + '\n')
                args.plan_file.chmod(0o600)
        else:
            if not args.plan_file:
                raise HostingError('apply requires --plan-file with a reviewed current plan')
            result = apply_plan(manifest, json.loads(args.plan_file.read_text()), names)
        print(json.dumps(result, indent=2))
        return 0 if result.get('ready', result.get('verified', True)) else 1
    except (HostingError, OSError, KeyError, ValueError) as error:
        print(json.dumps({'error': str(error)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
