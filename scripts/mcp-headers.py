#!/usr/bin/env python3
"""Provide Cloudflare auth to Codex internally; never run to display its output."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hosting import profile_environment, HostingError

try:
    env = profile_environment('cloudflare.default')
    token = env.get('CLOUDFLARE_API_TOKEN')
    print(json.dumps({'Authorization': 'Bearer ' + token} if token else {}))
except (OSError, HostingError):
    # Never print credential contents or diagnostics on the protocol output.
    sys.exit(1)
