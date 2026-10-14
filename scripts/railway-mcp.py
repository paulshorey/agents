#!/usr/bin/env python3
"""Start official Railway MCP with the existing explicit workspace profile."""
import os
from pathlib import Path
import shutil
import sys
from hosting import profile_environment, HostingError

try:
    # A different profile is an explicit caller choice; never fall back to the generic token.
    profile = sys.argv[1] if len(sys.argv) > 1 else str(Path.home() / '.config/railway/webarts.env')
    env = dict(os.environ)
    env.pop('RAILWAY_TOKEN', None)
    env.pop('RAILWAY_API_TOKEN', None)
    env = profile_environment(profile, env)
    if not env.get('RAILWAY_API_TOKEN'):
        raise HostingError('Missing Railway API credential in the selected workspace profile')
    executable = shutil.which('railway')
    if not executable:
        raise HostingError('Railway native CLI is not on PATH')
    os.execve(executable, [executable, 'mcp', 'local'], env)
except (OSError, HostingError) as error:
    print(str(error), file=sys.stderr)
    sys.exit(1)
