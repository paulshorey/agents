#!/usr/bin/env python3
"""Install managed config links without losing existing application settings."""
import argparse
from collections.abc import MutableMapping
import datetime as dt
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
import tempfile
import tomllib
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KEYS = {'model', 'model_reasoning_effort', 'model_verbosity',
                'model_reasoning_summary', 'web_search', 'service_tier'}


def toml_editor():
    """Load the deliberately pinned editor from ignored project-local packages."""
    directory = str(ROOT / 'local/python-packages')
    if directory not in sys.path:
        sys.path.insert(0, directory)
    try:
        import tomlkit
    except ImportError:
        raise ValueError('Restore the pinned Python packages using the README installation command.') from None
    pin = re.search(r'^tomlkit==([0-9.]+)', (ROOT / 'tools/python-requirements.txt').read_text(), re.MULTILINE)
    if not pin or tomlkit.__version__ != pin[1]:
        raise ValueError('Python editor version differs from its pin; restore packages using the README.')
    return tomlkit


def validate_mcp(servers):
    if not isinstance(servers, dict):
        raise ValueError('Shared MCP definitions must be a server mapping.')
    for name, server in servers.items():
        if not re.fullmatch(r'[a-z][a-z0-9_-]*', name) or not isinstance(server, dict):
            raise ValueError('Invalid shared MCP server definition.')
        if 'url' in server:
            try:
                url = urllib.parse.urlsplit(server['url']) if isinstance(server['url'], str) else None
                port = url.port if url else None
            except ValueError:
                raise ValueError('Malformed shared MCP HTTPS endpoint; inspect it locally.') from None
            valid = (set(server) == {'url'} and url and url.scheme == 'https' and url.hostname
                     and url.username is None and url.password is None and not url.fragment
                     and not any(re.search(r'token|secret|password|api.?key|authorization|^auth$|^key$|bearer', key, re.I)
                                 for key in urllib.parse.parse_qs(url.query)))
            if valid and name == 'cloudflare':
                # This server receives our Cloudflare bearer token through the auth helper.
                valid = url.hostname == 'mcp.cloudflare.com' and port in (None, 443) and url.path == '/mcp'
            if not valid:
                raise ValueError('Shared MCP HTTPS endpoints must be secret-free; Cloudflare auth requires its official MCP host.')
        elif not (set(server) <= {'command', 'args'} and isinstance(server.get('command'), str)
                  and server['command'] and isinstance(server.get('args', []), list)
                  and all(isinstance(arg, str) for arg in server.get('args', []))):
            raise ValueError('Shared MCP launchers require a command and string arguments; keep credentials local.')


def validate_links(root, definitions, home):
    targets = set()
    fixed = {'codex': ('local/codex/config.toml', '~/.codex/config.toml'),
             'shell': ('local/shell/zprofile', '~/.zprofile')}
    if not isinstance(definitions, list):
        raise ValueError('Managed links must be a list.')
    for link in definitions:
        if not isinstance(link, dict) or set(link) != {'source', 'target', 'kind'}:
            raise ValueError('A managed link needs source, target, and kind.')
        if not all(isinstance(value, str) and value for value in link.values()):
            raise ValueError('Managed link fields must be nonempty strings.')
        if link['kind'] not in ('codex', 'shell', 'json', 'text'):
            raise ValueError('Unsupported managed link kind.')
        source, raw = Path(link['source']), link['target']
        if not source.parts or source.is_absolute() or '..' in source.parts or not (root / source).resolve().is_relative_to(root.resolve()):
            raise ValueError('Managed link sources must stay inside the repository.')
        if link['kind'] in ('json', 'text') and (source.parts[0] in ('local', '.git')
                                               or 'node_modules' in source.parts or not (root / source).is_file()):
            raise ValueError('Shared text/JSON links require a shared source file, not ignored runtime or authentication state.')
        target = expand(raw, home)
        if not target.is_absolute() or '..' in target.parts or not target.is_relative_to(home):
            raise ValueError('Managed link targets must be absolute paths inside the selected home.')
        if target in targets:
            raise ValueError('Managed link targets must be unique.')
        targets.add(target)
        if link['kind'] in fixed and (link['source'], raw) != fixed[link['kind']]:
            raise ValueError('Codex and shell rendering have fixed source/target slots; add other files as generic links.')


def load_defaults(root):
    path = root / 'config/codex.defaults.toml'
    defaults = tomllib.loads(path.read_text()) if path.exists() else {}
    if set(defaults) - DEFAULT_KEYS or any(not isinstance(v, str) or not v or '\n' in v for v in defaults.values()):
        raise ValueError('Managed Codex defaults accept only documented non-secret preference keys with single-line string values.')
    return defaults


def render_defaults(text, defaults):
    """Replace only owned root keys, preserving unrelated TOML and comments."""
    current = tomllib.loads(text)
    changed = {key: value for key, value in defaults.items() if current.get(key) != value}
    if not changed:
        return text
    editor = toml_editor()
    document = editor.parse(text)
    for key, value in changed.items():
        document[key] = value
    result = editor.dumps(document)
    tomllib.loads(result)
    return result


def expand(value, home):
    return home / value[2:] if value.startswith('~/') else Path(value)


def render_codex(text, servers, root=ROOT):
    current = tomllib.loads(text)  # Reject invalid input before any write.
    validate_mcp(servers)
    actual = current.get('mcp_servers', {})
    if not isinstance(actual, dict):
        raise ValueError('Codex MCP configuration is not a table; inspect it locally.')
    wanted = {}
    for name, server in servers.items():
        wanted[name] = {**server, 'startup_timeout_sec': 30, 'tool_timeout_sec': 120}
        if name == 'cloudflare':
            helper = 'python3 ' + shlex.quote(str(root / 'scripts/mcp-headers.py'))
            wanted[name].update(bearer_token_env_var='CLOUDFLARE_API_TOKEN', http_headers_helper=helper)
    changed = {name: value for name, value in wanted.items() if actual.get(name) != value}
    if not changed:
        return text
    editor = toml_editor()
    document = editor.parse(text)
    mcp = document.setdefault('mcp_servers', editor.table())
    if not isinstance(mcp, MutableMapping):
        raise ValueError('Codex MCP configuration is not a table; inspect it locally.')
    for name, value in changed.items():
        item = editor.inline_table() if isinstance(mcp, editor.items.InlineTable) else editor.table()
        item.update(value)
        mcp[name] = item
    output = editor.dumps(document)
    tomllib.loads(output)
    return output


def atomic_write(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as file:
        temporary = Path(file.name)
        file.write(data)
    temporary.chmod(mode)
    temporary.replace(path)


def install(root=ROOT, home=Path.home(), apply=False):
    definitions = json.loads((root / 'config/links.json').read_text())['links']
    servers = json.loads((root / 'config/mcp.json').read_text())['mcpServers']
    validate_links(root, definitions, home)
    validate_mcp(servers)
    codex_target = home / '.codex/config.toml'
    current = codex_target.read_text() if codex_target.exists() else ''
    desired = render_codex(render_defaults(current, load_defaults(root)), servers, root)
    codex_source = root / 'local/codex/config.toml'
    problems = []
    if current != desired or not codex_source.exists() or codex_source.read_text() != desired:
        problems.append('Codex managed preferences or MCP sections need rendering')
    shell_target = home / '.zprofile'
    shell_current = shell_target.read_text() if shell_target.exists() else ''
    shell_hook = '[ -f "$HOME/.agents/config/env.sh" ] && . "$HOME/.agents/config/env.sh"'
    shell_desired = shell_current if shell_hook in shell_current else shell_current.rstrip() + '\n\n# Managed agent tool PATH (credentials are selected per task).\n' + shell_hook + '\n'
    shell_source = root / 'local/shell/zprofile'
    if shell_current != shell_desired or not shell_source.exists() or shell_source.read_text() != shell_desired:
        problems.append('Shell tool PATH hook needs rendering')
    for link in definitions:
        source, target = root / link['source'], expand(link['target'], home)
        if not target.is_symlink() or target.resolve() != source.resolve():
            problems.append(f'Link needed: {target}')
            parent = target.parent
            while not parent.exists():
                parent = parent.parent
            if apply and not os.access(parent, os.W_OK):
                raise ValueError(f'Link destination is not writable: {parent}. No configuration changed.')
        if link['kind'] not in ('codex', 'shell') and not source.exists():
            raise ValueError(f'Missing managed source: {source}')
        if link['kind'] == 'json' and target.exists():
            # Merge existing nonempty config only after it is explicitly migrated.
            raw = target.read_text().strip()
            if raw and json.loads(raw) != json.loads(source.read_text()):
                raise ValueError(f'{target} has other configuration. Merge it into {source} before installing.')
    if not problems:
        return {'status': 'current', 'links': len(definitions)}
    if not apply:
        return {'status': 'needs_install', 'changes': problems}
    local = root / 'local'
    local.mkdir(exist_ok=True)
    local.chmod(0o700)
    backup = local / 'install-backups' / dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup.mkdir(parents=True, mode=0o700)
    saved = []
    for index, link in enumerate(definitions):
        target = expand(link['target'], home)
        record = {'target': str(target), 'source': str(root / link['source']), 'existed': target.exists() or target.is_symlink()}
        if target.is_symlink():
            record['symlink'] = os.readlink(target)
            # The active Codex config may already point inside local/. Preserve its bytes too.
            if target.exists():
                shutil.copy2(target, backup / str(index))
                (backup / str(index)).chmod(0o600)
                record['file'] = str(index)
        elif target.exists():
            shutil.copy2(target, backup / str(index))
            record['file'] = str(index)
            record['mode'] = target.stat().st_mode & 0o777
            (backup / str(index)).chmod(0o600)
        saved.append(record)
    atomic_write(backup / 'manifest.json', json.dumps(saved, indent=2) + '\n')
    atomic_write(codex_source, desired)
    atomic_write(shell_source, shell_desired)
    for link in definitions:
        source, target = root / link['source'], expand(link['target'], home)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() and target.resolve() == source.resolve():
            continue
        temporary = target.with_name(target.name + '.agents-link')
        if temporary.exists() or temporary.is_symlink():
            raise ValueError(f'Unexpected temporary path: {temporary}')
        temporary.symlink_to(source)
        temporary.replace(target)
    # Keep installed bytes privately so restore can detect later application edits.
    for index, record in enumerate(saved):
        target = Path(record['target'])
        if target.is_file():
            installed_file = 'installed-' + str(index)
            shutil.copy2(target, backup / installed_file)
            (backup / installed_file).chmod(0o600)
            record['installed_file'] = installed_file
    atomic_write(backup / 'manifest.json', json.dumps(saved, indent=2) + '\n')
    return {'status': 'installed', 'backup': str(backup), 'links': len(definitions)}


def restore(backup):
    records = json.loads((backup / 'manifest.json').read_text())
    for record in records:
        target = Path(record['target'])
        if not target.is_symlink() or target.resolve() != Path(record['source']).resolve():
            raise ValueError(f'Refusing to overwrite a config changed after installation: {target}')
        if 'installed_file' in record and target.read_bytes() != (backup / record['installed_file']).read_bytes():
            raise ValueError('Installed configuration has newer edits; preserve or reconcile them before restoring.')
    for record in records:
        target = Path(record['target'])
        target.unlink()
        if 'symlink' in record:
            if 'file' in record:
                resolved = Path(record['source'])
                if Path(record['symlink']).is_absolute():
                    resolved = Path(record['symlink'])
                else:
                    resolved = target.parent / record['symlink']
                atomic_write(resolved.resolve(), (backup / record['file']).read_text())
            target.symlink_to(record['symlink'])
        elif 'file' in record:
            shutil.copy2(backup / record['file'], target)
            target.chmod(record.get('mode', 0o600))
    return {'status': 'restored', 'backup': str(backup)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Back up and install links; default checks only')
    parser.add_argument('--restore', type=Path, help='Restore one reported backup without overwriting later edits')
    args = parser.parse_args()
    try:
        result = restore(args.restore) if args.restore else install(apply=args.apply)
        print(json.dumps(result, indent=2))
        return 1 if result['status'] == 'needs_install' else 0
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
