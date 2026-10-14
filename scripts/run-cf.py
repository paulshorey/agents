#!/usr/bin/env python3
"""Run the pinned CLI with the explicit local Cloudflare profile, when present."""
import os
from pathlib import Path
import sys
from hosting import profile_environment, HostingError

root = Path(__file__).resolve().parents[1]
try:
    env = profile_environment(str(root / 'local/credentials/cloudflare.env'))
    command = root / 'tools/node_modules/.bin/cf'
    os.execve(command, [str(command), *sys.argv[1:]], env)
except (OSError, HostingError) as error:
    print(str(error), file=sys.stderr)
    sys.exit(1)
