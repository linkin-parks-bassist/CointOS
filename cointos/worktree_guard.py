"""Inherited write boundary for branch-publishing runs; reads stay unchanged."""
import ctypes
import json
import os
from pathlib import Path
import platform
import sys


def restrict(paths):
    if platform.machine() not in ('x86_64', 'aarch64'):
        raise RuntimeError('project write boundary needs supported Landlock syscall numbers')
    libc = ctypes.CDLL(None, use_errno=True)

    def checked(number, *args):
        result = libc.syscall(number, *args)
        if result < 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        return result

    if checked(444, None, 0, 1) < 3:
        raise RuntimeError('project write boundary requires Landlock ABI 3 or newer')
    writes = (1 << 1) | sum(1 << bit for bit in range(4, 15))

    class Ruleset(ctypes.Structure):
        _fields_ = [('handled_access_fs', ctypes.c_uint64)]

    class Beneath(ctypes.Structure):
        _pack_ = 1
        _fields_ = [('allowed_access', ctypes.c_uint64), ('parent_fd', ctypes.c_int32)]

    rules = Ruleset(writes)
    fd = checked(444, ctypes.byref(rules), ctypes.sizeof(rules), 0)
    try:
        for name in paths:
            path = Path(name).resolve(strict=True)
            rights = writes if path.is_dir() else (1 << 1) | (1 << 14)
            parent = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = Beneath(rights, parent)
                checked(445, fd, 1, ctypes.byref(rule), 0)
            finally:
                os.close(parent)
        if libc.prctl(38, 1, 0, 0, 0):
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        checked(446, fd, 0)
    finally:
        os.close(fd)


if __name__ == '__main__':
    restrict(json.loads(sys.argv[1]))
    os.execvpe(sys.argv[2], sys.argv[2:], os.environ)
