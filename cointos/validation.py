"""Execute one test after its output lease is acquired, and report how it ended.

This small subprocess runs inside the validation unit. Assertion exit codes are
data; a timeout or a unit killed before reporting is not an assertion failure.
"""
import json
from pathlib import Path
import subprocess
import sys
import time


def execute(command, limit, deadline):
    remaining = min(limit, deadline - time.monotonic())
    if remaining <= 0:
        return {'timeout': 'validation'}
    try:
        child = subprocess.Popen(command)
    except OSError as error:
        return {'error': str(error)}
    try:
        return {'code': child.wait(timeout=remaining)}
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()
        return {'timeout': 'command' if remaining == limit else 'validation'}


if __name__ == '__main__':
    report, limit, deadline, *command = sys.argv[1:]
    result = execute(command, float(limit), float(deadline))
    target = Path(report)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(result))
    temporary.replace(target)
