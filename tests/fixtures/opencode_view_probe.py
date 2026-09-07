#!/usr/bin/env python3
"""Real OpenCode server, inert run client: never requests inference."""
import json
import os
import sys

if sys.argv[1] == 'serve':
    os.execv('/home/david/.local/bin/opencode', ['opencode', *sys.argv[1:]])
assert '--attach' in sys.argv and '--session' in sys.argv
assert 'OPENCODE_CONFIG' not in os.environ
print(json.dumps({'type': 'probe_client', 'sessionID': sys.argv[sys.argv.index('--session')+1]}))
sys.exit(17)
