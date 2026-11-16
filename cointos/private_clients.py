"""Private client lifetime receipts: tmpfs metadata only, never conversation text."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from cointos import wakeups

DIRECTORY = Path('/dev/shm')


def register(directory: Path, key: str, pid: int | None = None) -> str:
    pid = os.getpid() if pid is None else pid
    process = wakeups.process(pid)
    if process is None or process['state'] == 'Z':
        raise ValueError('private client process is not alive')
    owner = 'private/' + hashlib.sha256(key.encode()).hexdigest()
    receipt = {'owner': owner, 'pid': pid, 'start_ticks': process['start_ticks'],
               'boot_id': wakeups.boot_id()}
    path = directory / 'client.json'
    temporary = directory / 'client.json.new'
    temporary.write_text(json.dumps(receipt))
    temporary.chmod(0o600)
    temporary.replace(path)
    return owner


def live(owner: str) -> bool:
    for path in DIRECTORY.glob('cointos-private-*/client.json'):
        try:
            receipt = json.loads(path.read_text())
            if receipt['owner'] != owner or receipt['boot_id'] != wakeups.boot_id():
                continue
            process = wakeups.process(receipt['pid'])
            if (process and process['state'] != 'Z'
                    and process['start_ticks'] == receipt['start_ticks']):
                return True
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return False
