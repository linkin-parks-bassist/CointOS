"""Private serialized JSON storage; schema and lifecycle belong to each caller."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
import uuid

def private(fd, directory=False):
    info = os.fstat(fd)
    if (not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077):
        raise ValueError('storage must be private and owned, with regular files')


def read(directory, filename, validate, fields, missing):
    try:
        descriptor = os.open(filename, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
    except FileNotFoundError:
        return missing
    try:
        private(descriptor)
        stream = os.fdopen(descriptor, 'r', encoding='utf-8')
    except BaseException:
        os.close(descriptor)
        raise
    with stream:
        data = json.load(stream, object_pairs_hook=fields,
                         parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON number')))
    return validate(data)


def write(directory, filename, data, validate):
    """Commit file contents and the replacement directory entry before returning."""
    validate(data)
    name = '.' + uuid.uuid4().hex + '.tmp'
    descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory)
    try:
        try:
            stream = os.fdopen(descriptor, 'w', encoding='utf-8')
        except BaseException:
            os.close(descriptor)
            raise
        with stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(data, stream, sort_keys=True, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, filename, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        try:
            os.unlink(name, dir_fd=directory)
        except FileNotFoundError:
            pass


def sync(directory, filename):
    # A prior directory-fsync failure can leave a visible event whose persistence
    # was never acknowledged. Replayed delivery must establish durability too.
    descriptor = os.open(filename, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
    try:
        private(descriptor)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.fsync(directory)


@contextmanager
def registry(directory, reader):
    path = Path(directory)
    missing, ancestor = [], path
    while not ancestor.exists() and not ancestor.is_symlink():
        missing.append(ancestor)
        ancestor = ancestor.parent
    for created in reversed(missing):
        created.mkdir(mode=0o700, exist_ok=True)
    # Retry visible ancestor links too: a previous failed fsync may have left
    # directories present without durably committing their names. No later
    # successful registration may acknowledge that incomplete creation.
    for enclosing in reversed(path.absolute().parents):
        parent = os.open(enclosing, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    lock = None
    try:
        private(descriptor, directory=True)
        lock = os.open('owner.lock', os.O_RDWR | os.O_CREAT | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
                       0o600, dir_fd=descriptor)
        private(lock)
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield descriptor, reader(descriptor)
    finally:
        if lock is not None:
            os.close(lock)
        os.close(descriptor)

