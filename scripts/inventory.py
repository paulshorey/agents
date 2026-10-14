#!/usr/bin/env python3
"""Discover configuration references and check registered state without printing secrets."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


class InventoryError(Exception):
    pass


def read_data(path):
    try:
        return tomllib.loads(path.read_text()) if path.suffix == '.toml' else json.loads(path.read_text())
    except (OSError, ValueError):
        # Parser exceptions can quote an offending line containing a secret.
        raise InventoryError('Cannot read a configuration data file; inspect it locally.') from None


def schema_check(value, schema, definitions, path='$'):
    """Validate the explicit JSON Schema keyword subset used by our schema.

    No third-party runtime is needed. Unknown keywords fail closed so future
    schema changes cannot silently weaken validation.
    """
    allowed = {'$schema', '$id', '$defs', '$ref', 'title', 'description', 'type',
               'properties', 'required', 'additionalProperties', 'items',
               'enum', 'const', 'pattern', 'minLength', 'minItems', 'uniqueItems'}
    if set(schema) - allowed:
        raise InventoryError('Unsupported schema keyword; update the validator first.')
    if '$ref' in schema:
        prefix = '#/$defs/'
        if not schema['$ref'].startswith(prefix):
            raise InventoryError('Only local schema references are supported.')
        return schema_check(value, definitions[schema['$ref'][len(prefix):]], definitions, path)
    types = {'object': dict, 'array': list, 'string': str, 'integer': int, 'boolean': bool}
    kind = schema.get('type')
    if kind and (not isinstance(value, types[kind]) or (kind == 'integer' and isinstance(value, bool))):
        raise InventoryError(f'{path}: wrong type')
    if 'enum' in schema and value not in schema['enum']:
        raise InventoryError(f'{path}: unsupported choice')
    if 'const' in schema and (type(value) is not type(schema['const']) or value != schema['const']):
        raise InventoryError(f'{path}: unexpected constant')
    if isinstance(value, str):
        if len(value) < schema.get('minLength', 0) or ('pattern' in schema and not re.search(schema['pattern'], value)):
            raise InventoryError(f'{path}: invalid text format')
    if isinstance(value, dict):
        properties = schema.get('properties', {})
        if set(schema.get('required', [])) - set(value):
            raise InventoryError(f'{path}: required metadata missing')
        if schema.get('additionalProperties') is False and set(value) - set(properties):
            raise InventoryError(f'{path}: unexpected field; secret values are not inventory metadata')
        for key, item in value.items():
            if key in properties:
                schema_check(item, properties[key], definitions, f'{path}.{key}')
    if isinstance(value, list):
        if len(value) < schema.get('minItems', 0):
            raise InventoryError(f'{path}: too few items')
        if schema.get('uniqueItems') and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            raise InventoryError(f'{path}: duplicate items')
        for index, item in enumerate(value):
            schema_check(item, schema.get('items', {}), definitions, f'{path}[{index}]')


def repo_path(root, path):
    candidate = root / path
    if not Path(path).parts or Path(path).is_absolute() or '..' in Path(path).parts or not candidate.resolve().is_relative_to(root.resolve()):
        raise InventoryError('A shared reference must stay inside the repository.')
    if Path(path).parts[0] in ('local', '.git') or 'node_modules' in Path(path).parts:
        raise InventoryError('Shared references cannot read ignored state or credentials.')
    return candidate


def referenced(root, reference):
    value = read_data(repo_path(root, reference['file']))
    pointer = reference.get('pointer', '')
    try:
        for part in pointer.split('/')[1:] if pointer else []:
            part = part.replace('~1', '/').replace('~0', '~')
            value = value[int(part)] if isinstance(value, list) else value[part]
    except (KeyError, IndexError, ValueError, TypeError):
        raise InventoryError('A declared configuration reference no longer resolves.') from None
    return value


def load_inventory(root=ROOT):
    data = read_data(root / 'config/inventory.json')
    schema = read_data(root / 'config/inventory.schema.json')
    schema_check(data, schema, schema['$defs'])
    entries = data['entries']
    registered_files = set()
    ids = [entry['id'] for entry in entries]
    if len(ids) != len(set(ids)):
        raise InventoryError('Inventory IDs must be unique.')
    for entry in entries:
        if set(entry.get('consumers', [])) - set(ids):
            raise InventoryError(f'{entry["id"]}: unknown consumer')
        if not repo_path(root, entry['runbook']).is_file():
            raise InventoryError(f'{entry["id"]}: missing update instructions')
        for reference in entry.get('references', []):
            registered_files.add(reference['file'])
            if not repo_path(root, reference['file']).is_file():
                raise InventoryError(f'{entry["id"]}: missing source reference')
            if 'pointer' in reference:
                referenced(root, reference)
        if 'path_ref' in entry and not isinstance(referenced(root, entry['path_ref']), str):
            raise InventoryError(f'{entry["id"]}: location reference must resolve to a path')
        if 'path_ref' in entry and 'path' in entry:
            raise InventoryError(f'{entry["id"]}: declare a path or a reference, not both')
        if entry['kind'] == 'credential' and (not (entry.get('path') or entry.get('path_ref')) or not entry.get('variables')):
            raise InventoryError(f'{entry["id"]}: credential location or variable names missing')
        if 'path_ref' in entry:
            registered_files.add(entry['path_ref']['file'])
        if entry.get('plugins') and len({p['id'] for p in entry['plugins']}) != len(entry['plugins']):
            raise InventoryError('Registered plugin IDs must be unique.')
    missing = [p for p in (root / 'config').rglob('*')
               if p.is_file() and p.suffix in ('.json', '.toml', '.sh')
               and str(p.relative_to(root)) not in registered_files]
    if missing:
        raise InventoryError('Unregistered shared configuration file; add its reference to the inventory.')
    links = read_data(root / 'config/links.json')['links']
    indexes = [entry['link_index'] for entry in entries if 'link_index' in entry]
    if sorted(indexes) != list(range(len(links))):
        raise InventoryError('Every managed link must have exactly one inventory entry.')
    import install
    from hosting import resolve_profile, HostingError
    try:
        install.validate_links(root, links, Path.home())
        install.load_defaults(root)
        servers = read_data(root / 'config/mcp.json')['mcpServers']
        install.validate_mcp(servers)
        for name in servers:
            pointer = '/mcpServers/' + name.replace('~', '~0').replace('/', '~1')
            if not any(ref.get('file') == 'config/mcp.json' and ref.get('pointer') == pointer
                       for entry in entries for ref in entry.get('references', [])):
                raise InventoryError('Unregistered shared MCP server; add its specific definition reference.')
        profiles = read_data(root / 'config/profiles.json')['profiles']
        for name in profiles:
            resolve_profile(name, root)
    except (OSError, ValueError, KeyError, TypeError, HostingError):
        raise InventoryError('Managed defaults, links, MCP definitions, or profiles are invalid; inspect their source files.') from None
    return data


def location(entry, root=ROOT, home=None):
    raw = referenced(root, entry['path_ref']) if 'path_ref' in entry else entry.get('path')
    if raw is None:
        return None
    if raw.startswith('~/'):
        return (home or Path.home()) / raw[2:]
    return Path(raw) if Path(raw).is_absolute() else root / raw


def displayed_entry(entry, root=ROOT):
    result = dict(entry)
    if 'path_ref' in entry:
        result['resolved_path'] = referenced(root, entry['path_ref'])
    if 'link_index' in entry:
        result['link'] = read_data(root / 'config/links.json')['links'][entry['link_index']]
    return result


def catalogs(root=ROOT):
    """Catalog shared files only; never traverse application auth state."""
    imports = {item['skill']: item for item in read_data(root / 'config/skill-sources.json')}
    skills = []
    for path in sorted((root / 'skills').glob('*/SKILL.md')):
        name = path.parent.name
        source = imports.get(name)
        skills.append({'name': name, 'path': str(path.relative_to(root)),
                       'source': source['repository'] if source else 'local',
                       'revision': source['commit'] if source else 'Git history',
                       'adaptations': source.get('local_changes', []) if source else []})
    helpers = [str(path.relative_to(root)) for folder in ('bin', 'scripts')
               for path in sorted((root / folder).glob('*')) if path.is_file() and path.suffix != '.pyc']
    return {'skills': skills, 'helpers': helpers}


def md(value):
    return str(value).replace('|', '\\|').replace('\n', ' ').replace('`', '\\`')


def documentation(data, root=ROOT):
    lines = ['# Configuration inventory', '',
             '<!-- Generated by agents-config docs. Edit config/inventory.json and its referenced manifests. -->', '',
             'This lists declared configuration and update instructions, not current authentication status.',
             'Secret values, OAuth state, backups, and machine check results are never included.', '',
             'Start with `agents-config list`, `agents-config show ITEM`, or `agents-config check`.',
             'Use `check --live` for registered provider reads. Checks never apply configuration.', '',
             '| Item | Kind | Owner | Location or source | Update instructions |',
             '| --- | --- | --- | --- | --- |']
    for entry in data['entries']:
        shown = displayed_entry(entry, root)
        if 'link' in shown:
            where = shown['link']['source'] + ' → ' + shown['link']['target']
        else:
            where = shown.get('resolved_path') or entry.get('path') or ', '.join(r['file'] for r in entry.get('references', [])) or 'Application-managed'
        lines.append(f'| [{md(entry["id"])}](#{entry["id"].replace(".", "-")}) | {entry["kind"]} | {entry["owner"]} | {md(where)} | [{md(entry["runbook"])}](../{entry["runbook"]}) |')
    for entry in data['entries']:
        lines += ['', f'<a id="{entry["id"].replace(".", "-")}"></a>', '',
                  f'## {entry["id"]}', '', entry['description'], '', f'Owner: **{entry["owner"]}**.']
        shown = displayed_entry(entry, root)
        if 'link' in shown:
            link = shown['link']
            lines += ['', f'Source: `{link["source"]}`. Installed at `{link["target"]}`. Installer kind: `{link["kind"]}`.']
        elif shown.get('resolved_path') or entry.get('path'):
            lines += ['', 'Location: `' + md(shown.get('resolved_path') or entry['path']) + '`.']
        for key, label in [('variables', 'Variable names'), ('permissions', 'Declared permissions'), ('consumers', 'Consumers')]:
            if entry.get(key):
                lines += ['', label + ': ' + ', '.join('`' + md(v) + '`' for v in entry[key]) + '.']
        if entry.get('plugins'):
            lines += ['', 'Registered plugin enablement (application-owned; use checks for current state):', '',
                      '| Plugin | Registered enabled |', '| --- | --- |']
            lines += [f'| {md(plugin["id"])} | {str(plugin["enabled"]).lower()} |' for plugin in entry['plugins']]
        if entry.get('mcp_servers'):
            lines += ['', 'Registered application MCP runtimes: ' + ', '.join('`' + md(name) + '`' for name in entry['mcp_servers']) + '.']
        for note in entry.get('notes', []):
            lines += ['', note]
        lines += ['', f'[Update and recovery instructions](../{entry["runbook"]}).']
    derived = catalogs(root)
    lines += ['', '## Skills', '', 'Derived from local skill entrypoints and `config/skill-sources.json`.', '',
              '| Skill | Entrypoint | Source | Revision |', '| --- | --- | --- | --- |']
    for skill in derived['skills']:
        lines.append(f'| {md(skill["name"])} | [{md(skill["path"])}](../{skill["path"]}) | {md(skill["source"])} | {md(skill["revision"])} |')
        if skill['adaptations']:
            lines.append(f'| Local adaptations | {md("; ".join(skill["adaptations"]))} | | |')
    lines += ['', '## Utility files', '', 'Derived from `bin/` and `scripts/`. See the utility runbook before executing a helper.', '']
    lines += [f'- [{path}](../{path})' for path in derived['helpers']]
    return '\n'.join(lines) + '\n'


def local_checks(data, root=ROOT, home=None):
    from hosting import profile_environment, HostingError
    import install
    home = home or Path.home()
    results = []
    def record(id, passed, detail):
        results.append({'id': id, 'passed': passed, 'detail': detail})
    for entry in data['entries']:
        path = location(entry, root, home)
        if entry['kind'] == 'credential':
            passed = bool(path and path.is_file())
            detail = 'present' if passed else 'missing; follow the credential runbook'
            if passed:
                info = path.stat()
                passed = info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600
                detail = 'owner-only mode 600' if passed else 'ownership or permissions differ'
                if passed:
                    try:
                        env = profile_environment(str(path), {})
                        missing = [v for v in entry['variables'] if not env.get(v)]
                        passed = not missing
                        detail = 'required variable names present' if passed else 'required variable names missing'
                    except (HostingError, OSError, ValueError):
                        passed, detail = False, 'profile format invalid; inspect locally'
                if path.resolve().is_relative_to(root.resolve()):
                    ignored = subprocess.run(['git', '-C', str(root), 'check-ignore', '-q', str(path)], capture_output=True).returncode == 0
                    passed = passed and ignored and stat.S_IMODE(path.parent.stat().st_mode) == 0o700
                    if not passed:
                        detail = 'check profile, Git ignore, and credential directory permissions'
            record(entry['id'], passed, detail)
        elif 'link_index' in entry:
            link = read_data(root / 'config/links.json')['links'][entry['link_index']]
            target = install.expand(link['target'], home)
            passed = target.is_symlink() and target.resolve() == (root / link['source']).resolve()
            record(entry['id'], passed, 'link current' if passed else 'link missing or different; run installer check')
        elif entry.get('plugins'):
            try:
                active = read_data(home / '.codex/config.toml').get('plugins', {})
                passed = (set(active) == {plugin['id'] for plugin in entry['plugins']}
                          and all(active.get(plugin['id'], {}).get('enabled') is plugin['enabled'] for plugin in entry['plugins']))
                record(entry['id'], passed, 'registered toggles match' if passed else 'plugin toggles differ; review and update intended metadata')
            except (InventoryError, AttributeError, TypeError):
                record(entry['id'], False, 'application plugin settings unavailable; inspect locally')
        elif entry.get('mcp_servers'):
            try:
                active = read_data(home / '.codex/config.toml').get('mcp_servers', {})
                shared = read_data(root / 'config/mcp.json')['mcpServers']
                passed = isinstance(active, dict) and set(active) == set(shared) | set(entry['mcp_servers'])
                record(entry['id'], passed, 'registered runtimes match' if passed else 'MCP runtimes differ; review registration')
            except InventoryError:
                record(entry['id'], False, 'application MCP configuration unavailable; inspect locally')
    try:
        state = install.install(root=root, home=home)
        record('configuration.rendering', state['status'] == 'current', state['status'])
    except (OSError, ValueError):
        record('configuration.rendering', False, 'configuration could not be checked; inspect locally')
    try:
        installed = read_data(root / 'tools/node_modules/cf/package.json')['version']
        pinned = read_data(root / 'tools/package.json')['dependencies']['cf']
        passed = (root / 'tools/node_modules/.bin/cf').is_file() and installed == pinned
        record('cloudflare.cli', passed, 'pinned CLI version matches' if passed else 'restore CLI from the lockfile')
    except (InventoryError, KeyError):
        record('cloudflare.cli', False, 'restore CLI from the lockfile')
    try:
        install.toml_editor()
        record('tools.python', True, 'pinned TOML editor available')
    except (OSError, ValueError):
        record('tools.python', False, 'restore pinned Python packages using the README')
    record('railway.cli', bool(shutil.which('railway')), 'native CLI availability on PATH')
    return results


def mcp_read(token, account_id, zone_name, endpoint='https://mcp.cloudflare.com/mcp'):
    """Fixed read-only protocol probe; raw provider errors/results never leave here."""
    import install
    install.validate_mcp({'cloudflare': {'url': endpoint}})
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json',
               'Accept': 'application/json, text/event-stream', 'User-Agent': 'paul-agents-hosting/1'}
    def rpc(method, params, id):
        body = json.dumps({'jsonrpc': '2.0', 'id': id, 'method': method, 'params': params}).encode()
        request = urllib.request.Request(endpoint, data=body, headers=headers, method='POST')
        with urllib.request.urlopen(request, timeout=30) as response:
            session = response.headers.get('Mcp-Session-Id')
            if session:
                headers['Mcp-Session-Id'] = session
            raw = response.read(262144).decode()
        messages = [json.loads(raw)] if raw.lstrip().startswith('{') else [json.loads(line[6:]) for line in raw.splitlines() if line.startswith('data: ') and line[6:].strip()]
        message = next((item for item in messages if item.get('id') == id), None)
        if not message or 'error' in message or message.get('result', {}).get('isError'):
            raise InventoryError('Cloudflare MCP probe failed.')
        return message['result']
    rpc('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 'paul-agents-hosting', 'version': '1'}}, 1)
    path = '/zones?' + urllib.parse.urlencode({'account.id': account_id, 'name': zone_name, 'per_page': 50})
    code = ('async () => { const r = await cloudflare.request({method:"GET",path:' + json.dumps(path)
            + '}); return {success:r.success,matched:r.result?.length===1&&r.result[0].name==='
            + json.dumps(zone_name) + '&&r.result[0].account.id===' + json.dumps(account_id) + '}; }')
    result = rpc('tools/call', {'name': 'execute', 'arguments': {'code': code, 'account_id': account_id}}, 2)
    content = next(item['text'] for item in result.get('content', []) if item.get('type') == 'text')
    data = json.loads(content)
    return data.get('success') is True and data.get('matched') is True


def live_checks(root=ROOT, manifest_path=None):
    from hosting import Cloudflare, load_manifest, profile_environment, railway_env, railway_project
    manifest = load_manifest(manifest_path or root / 'config/hosting/paul.json')
    endpoint = read_data(root / 'config/mcp.json')['mcpServers']['cloudflare']['url']
    results = []
    for id, probe in [
        ('cloudflare.api', lambda: cloudflare_access(manifest, Cloudflare, profile_environment)),
        ('cloudflare.mcp', lambda: mcp_read(profile_environment(manifest['cloudflare']['profile'], {}).get('CLOUDFLARE_API_TOKEN', ''), manifest['cloudflare']['account_id'], manifest['cloudflare']['zone_name'], endpoint)),
        ('railway.project', lambda: bool(railway_project(manifest, railway_env(manifest))))
    ]:
        try:
            passed = bool(probe())
            item = {'id': id, 'passed': passed, 'detail': 'registered provider read succeeded' if passed else 'provider read did not confirm access'}
            if id == 'cloudflare.api':
                item['dns_edit_verified'] = False
                item['detail'] = ('token, identity, zone, and DNS record reads succeeded; DNS Edit is declared, not tested'
                                  if passed else item['detail'])
            results.append(item)
        except Exception as error:
            # Never print exception messages or provider bodies, even on CLI failures.
            results.append({'id': id, 'passed': False, 'detail': 'provider read failed', 'error_type': type(error).__name__})
    return results


def cloudflare_access(manifest, client_type, profile_loader):
    env = profile_loader(manifest['cloudflare']['profile'], {})
    client = client_type(manifest, env)
    zone = client.zone()
    verified = client.request('GET', '/user/tokens/verify')['result'].get('status') == 'active'
    client.request('GET', '/user')
    # Zone.permissions is deprecated legacy membership data, not token grants.
    # A real DNS GET proves read access only; writes require task authorization.
    client.request('GET', '/zones/' + zone['id'] + '/dns_records?per_page=1')
    return verified


def save_status(root, result):
    from install import atomic_write
    directory = root / 'local/inventory'
    if not directory.resolve().is_relative_to((root / 'local').resolve()) or directory.is_symlink():
        raise InventoryError('Status output must stay in local/inventory.')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    atomic_write(directory / 'status.json', json.dumps(result, indent=2) + '\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest='command', required=True)
    listing = sub.add_parser('list', help='Search metadata, never secret contents')
    listing.add_argument('query', nargs='?', default='')
    showing = sub.add_parser('show', help='Display locations, consumers, and update instructions')
    showing.add_argument('id')
    sub.add_parser('validate', help='Validate registered references without reading local credentials')
    docs = sub.add_parser('docs', help='Generate the tracked Markdown inventory')
    docs.add_argument('--check', action='store_true', help='Fail if generated documentation is stale; do not write')
    check = sub.add_parser('check', help='Read-only local checks; optional registered provider reads')
    check.add_argument('--live', action='store_true')
    check.add_argument('--manifest', type=Path, help='Explicit hosting manifest for live checks; default: config/hosting/paul.json')
    check.add_argument('--save-status', action='store_true', help='Save sanitized results in ignored local/inventory/status.json')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        data = load_inventory(root)
        if args.command == 'list':
            entries = [entry for entry in data['entries'] if args.query.lower() in json.dumps(entry).lower()]
            print(json.dumps([{'id': e['id'], 'kind': e['kind'], 'description': e['description']} for e in entries], indent=2))
        elif args.command == 'show':
            entry = next((e for e in data['entries'] if e['id'] == args.id), None)
            if entry is None:
                raise InventoryError('Unknown inventory ID; use agents-config list.')
            print(json.dumps(displayed_entry(entry, root), indent=2))
        elif args.command == 'validate':
            print(json.dumps({'valid': True, 'entries': len(data['entries']), 'skills': len(catalogs(root)['skills'])}))
        elif args.command == 'docs':
            text = documentation(data, root)
            path = root / 'docs/INVENTORY.md'
            if args.check:
                if not path.is_file() or path.read_text() != text:
                    raise InventoryError('Generated inventory is stale; run agents-config docs.')
                print('Generated inventory is current.')
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
                print('Generated docs/INVENTORY.md.')
        else:
            if args.manifest and not args.live:
                raise InventoryError('--manifest selects a live target; use it with --live.')
            results = local_checks(data, root)
            if args.live:
                manifest_path = (args.manifest or root / 'config/hosting/paul.json').expanduser().resolve()
                results.extend(live_checks(root, manifest_path))
            result = {'checked_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'live': args.live,
                      'passed': all(item['passed'] for item in results), 'results': results}
            if args.live:
                result['manifest'] = str(manifest_path)
                result['write_permissions_verified'] = False
            if args.save_status:
                save_status(root, result)
            print(json.dumps(result, indent=2))
            return 0 if result['passed'] else 1
        return 0
    except (InventoryError, OSError, ValueError, KeyError) as error:
        print(str(error) if isinstance(error, InventoryError) else 'Inventory could not be processed; inspect configuration locally.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
