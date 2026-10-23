"""Keep validated requests and runtime replacement on opposite sides of one lease."""
from contextlib import contextmanager
import fcntl
import os
import stat


@contextmanager
def lease(root, *, shared=False):
    """Requests share ownership through settlement; daemon replacement is exclusive.

    Admission never waits while holding the daemon's ledger lock. A failed
    acquisition changes no runtime state; closing the descriptor releases it.
    The separate repair/installation lease still serializes installers and repair.
    """
    directory = root / 'state'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(directory / 'replacement.lock',
                         os.O_CREAT | os.O_RDWR | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ValueError('replacement owner is not a regular file')
    with os.fdopen(descriptor, 'r+') as owner:
        try:
            fcntl.flock(owner, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True
