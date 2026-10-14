#!/usr/bin/env python3
"""Interactively store a Cloudflare token without exposing it in arguments/output."""
import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import tempfile
from hosting import ROOT, Cloudflare, HostingError, load_manifest, resolve_profile


def credential_text(token, zone, pin_zone=False):
    text = f'CLOUDFLARE_API_TOKEN={token}\nCLOUDFLARE_ACCOUNT_ID={zone["account_id"]}\n'
    if pin_zone:
        text += f'CLOUDFLARE_ZONE_ID={zone["id"]}\n'
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', default=str(ROOT / 'config/hosting/paul.json'))
    parser.add_argument('--pin-zone', action='store_true', help='Set a global zone default for a deliberately single-zone profile')
    args = parser.parse_args()
    try:
        manifest = load_manifest(args.manifest)
        if not sys.stdin.isatty():
            raise HostingError('Run this command in your terminal so token entry is hidden')
        token = getpass.getpass('Cloudflare scoped API token (hidden): ').strip()
        if not token or not token.isascii() or any(ch.isspace() for ch in token):
            raise HostingError('Invalid token format')
        # Skip any old profile during validation; only the newly entered token is tested.
        checking = json.loads(json.dumps(manifest))
        checking['cloudflare']['profile'] = '/nonexistent-profile-for-validation'
        zone = Cloudflare(checking, {'CLOUDFLARE_API_TOKEN': token}).zone()
        target = resolve_profile(manifest['cloudflare']['profile'])
        if not target.resolve().is_relative_to((ROOT / 'local').resolve()):
            raise HostingError('Credential setup writes only inside ignored ~/.agents/local/')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.parent.chmod(0o700)
        with tempfile.NamedTemporaryFile(mode='w', dir=target.parent, delete=False) as file:
            temp = Path(file.name)
            file.write(credential_text(token, zone, args.pin_zone))
        temp.chmod(0o600)
        temp.replace(target)
        print(json.dumps({'stored': str(target), 'zone': zone}, indent=2))
        return 0
    except (HostingError, OSError, ValueError, EOFError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
