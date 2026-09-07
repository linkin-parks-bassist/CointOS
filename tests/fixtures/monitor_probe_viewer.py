#!/usr/bin/env python3
"""Inert viewer for monitor handover tests; no model or network calls."""
import sys
import time

print('ATTACHED '+sys.argv[sys.argv.index('--session')+1], flush=True)
while True:
    time.sleep(1)
