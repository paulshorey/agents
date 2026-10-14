#!/usr/bin/env python3
"""Install managed config links without losing existing application settings."""
import argparse
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

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KEYS = {'model', 'model_reasoning_effort', 'model_verbosity',
                'model_reasoning_summary', 'web_search', 'service_tier'}


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
    lines, kept, index = text.splitlines(keepends=True), [], 0
    while index < len(lines):
        start = index
        line = lines[index]
        if not line.strip() or line.lstrip().startswith('#'):
            kept.append(line)
            index += 1
            continue
        if line.lstrip().startswith('['):
            kept.extend(lines[index:])
            break
        # Parse complete root assignments, including multiline strings/arrays.
        while index < len(lines):
            index += 1
            try:
                statement = tomllib.loads(''.join(lines[start:index]))
                break
            except tomllib.TOMLDecodeError:
                if index == len(lines):
                    raise ValueError('Could not preserve a root TOML assignment.')
        if len(statement) != 1 or next(iter(statement)) not in changed:
            kept.extend(lines[start:index])
    prefix = ''.join(f'{key} = {json.dumps(value)}\n' for key, value in changed.items())
    result = prefix + ''.join(kept)
    tomllib.loads(result)
    return result


def expand(value, home):
    return home / value[2:] if value.startswith('~/') else Path(value)


def render_codex(text, servers, root=ROOT):
    tomllib.loads(text)  # Reject invalid input rather than silently discarding it.
    lines, skip = [], False
    for line in text.splitlines(keepends=True):
        match = re.match(r'^\s*\[([^\]]+)\]', line)
        if match:
            section = match[1]
            skip = any(section == f'mcp_servers.{name}' or section.startswith(f'mcp_servers.{name}.') for name in servers)
        if not skip:
            lines.append(line)
    output = ''.join(lines).rstrip() + '\n'
    for name, server in servers.items():
        if not re.fullmatch(r'[a-z][a-z0-9_-]*', name):
            raise ValueError(f'Invalid managed server name: {name}')
        output += f'\n[mcp_servers.{name}]\n'
        for key in ('url', 'command', 'args'):
            if key in server:
                output += f'{key} = {json.dumps(server[key])}\n'
        output += 'startup_timeout_sec = 30\ntool_timeout_sec = 120\n'
        if name == 'cloudflare':
            output += 'bearer_token_env_var = "CLOUDFLARE_API_TOKEN"\n'
            helper = 'python3 ' + shlex.quote(str(root / 'scripts/mcp-headers.py'))
            output += 'http_headers_helper = ' + json.dumps(helper) + '\n'
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
    for server in servers.values():
        valid_http = set(server) == {'url'} and server['url'].startswith('https://') if 'url' in server else False
        valid_stdio = set(server) <= {'command', 'args'} and isinstance(server.get('command'), str) and isinstance(server.get('args', []), list)
        if not (valid_http or valid_stdio):
            raise ValueError('Shared MCP definitions accept HTTPS URLs or command/args only; keep credentials local.')
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
    return {'status': 'installed', 'backup': str(backup), 'links': len(definitions)}


def restore(backup):
    records = json.loads((backup / 'manifest.json').read_text())
    for record in records:
        target = Path(record['target'])
        if not target.is_symlink() or target.resolve() != Path(record['source']).resolve():
            raise ValueError(f'Refusing to overwrite a config changed after installation: {target}')
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
