"""Coin's local filesystem operations, using the workstation user's permissions."""
import fnmatch
import hashlib
import os
from pathlib import Path
import shutil
import stat
import tempfile



def path(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('a nonempty filesystem path is required')
    return Path(value).expanduser().absolute()


def info(value):
    target = path(str(value))
    record = target.lstat()
    kind = ('symlink' if stat.S_ISLNK(record.st_mode) else 'directory' if stat.S_ISDIR(record.st_mode)
            else 'file' if stat.S_ISREG(record.st_mode) else 'special')
    return {'path': str(target), 'name': target.name, 'kind': kind,
            'size': record.st_size, 'modified_at': record.st_mtime}


def publish(target, writer, overwrite=False):
    """Commit a complete regular file, refusing collisions unless explicitly requested."""
    target = path(str(target))
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ValueError('destination must be a regular file')
    descriptor, temporary = tempfile.mkstemp(prefix='.coin-', dir=target.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            writer(stream)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            if target.exists():
                os.chmod(temporary, stat.S_IMODE(target.stat().st_mode))
            os.replace(temporary, target)
        else:
            os.link(temporary, target)
        directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def execute(name, arguments):
    target = path(arguments['path'])
    if name == 'fs_transfer':
        operation = arguments['operation']
        if operation not in ('copy', 'move'):
            raise ValueError('operation must be copy or move')
        verification = arguments.get('verification', 'normal')
        if verification not in ('normal', 'hash'):
            raise ValueError('verification must be normal or hash')
        destination = path(arguments['destination'])
        sources = [path(str(child)) for child in sorted(target.iterdir())
                   if fnmatch.fnmatch(child.name, arguments.get('glob', '*'))]
        sources = [child for child in sources if child.is_file() and not child.is_symlink()]
        destination.mkdir(parents=True, exist_ok=True)
        result = {'ok': True, 'transferred': 0, 'already_present': 0, 'failed': 0,
                  'destination': str(destination), 'operation': operation, 'first_failure': None}
        for source in sources:
            try:
                into = destination / source.name
                if source == into:
                    result['already_present'] += 1
                    continue
                if into.exists():
                    raise FileExistsError('destination already exists; existing file preserved')
                expected = None
                if verification == 'hash':
                    with source.open('rb') as stream:
                        expected = hashlib.file_digest(stream, 'sha256').hexdigest()
                execute('fs_copy' if expected else 'fs_' + operation, {'path': str(source), 'destination': str(into)})
                if expected:
                    with into.open('rb') as stream:
                        if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                            raise ValueError('verification failed; source preserved')
                    if operation == 'move':
                        source.unlink()
                result['transferred'] += 1
            except (OSError, ValueError) as error:
                result['failed'] += 1
                result['first_failure'] = result['first_failure'] or {'path': str(source), 'error': str(error)}
        result['ok'] = not result['failed']
        return result
    if name == 'fs_stat':
        return {'ok': True, **info(target)}
    if name == 'fs_list':
        offset, limit = arguments.get('offset', 0), arguments.get('limit', 20)
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError('offset must be nonnegative and limit between 1 and 20')
        entries = []
        for child in sorted(target.iterdir()):
            try:
                entries.append(info(child))
            except PermissionError:
                continue
        end = offset + limit
        return {'ok': True, 'path': str(target), 'total_entries': len(entries),
                'offset': offset, 'next_offset': end if end < len(entries) else None,
                'entries': entries[offset:end]}
    if name == 'fs_read':
        if not target.is_file():
            raise ValueError('read requires a regular text file')
        start, count = arguments.get('start_line', 1), arguments.get('lines')
        if type(start) is not int or start < 1 or (count is not None and (type(count) is not int or count < 1)):
            raise ValueError('line numbers and counts must be positive integers')
        lines = target.read_text(encoding='utf-8').splitlines(keepends=True)
        return {'ok': True, 'path': str(target), 'start_line': start, 'total_lines': len(lines),
                'content': ''.join(lines[start - 1:None if count is None else start - 1 + count])}
    if name == 'fs_search':
        matches = []
        pattern, text = arguments.get('glob', '*'), arguments.get('text')
        def failed(error):
            raise error
        for parent, dirs, files in os.walk(target, followlinks=False, onerror=failed):
            for filename in files:
                candidate = Path(parent) / filename
                if not fnmatch.fnmatch(filename, pattern) or not candidate.is_file():
                    continue
                if text is None:
                    matches.append({'path': str(candidate)})
                else:
                    try:
                        with candidate.open(encoding='utf-8') as stream:
                            matches.extend({'path': str(candidate), 'line': number, 'text': line.rstrip('\n')}
                                           for number, line in enumerate(stream, 1) if text in line)
                    except UnicodeError:
                        continue
        return {'ok': True, 'matches': matches}
    if name == 'fs_mkdir':
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
    elif name == 'fs_write':
        content = arguments['content'].encode('utf-8')
        publish(target, lambda stream: stream.write(content), arguments.get('overwrite', False))
    elif name in ('fs_copy', 'fs_move'):
        destination = path(arguments['destination'])
        if destination.exists() or destination.is_symlink():
            raise FileExistsError('destination already exists; choose an unused destination')
        if target.is_dir() and not target.is_symlink():
            if target.resolve() in destination.resolve().parents:
                raise ValueError('destination cannot be inside the source directory')
            shutil.copytree(target, destination, symlinks=True)
            if name == 'fs_move':
                shutil.rmtree(target)
        elif target.is_file():
            with target.open('rb') as source:
                publish(destination, lambda stream: shutil.copyfileobj(source, stream))
            if name == 'fs_move':
                target.unlink()
        else:
            raise ValueError('copy/move requires a regular file or directory')
        return {'ok': True, 'source': str(target), **info(destination)}
    elif name == 'fs_remove':
        if target.is_dir() and not target.is_symlink():
            if arguments.get('recursive', False):
                shutil.rmtree(target)
            else:
                target.rmdir()
        else:
            target.unlink()
        return {'ok': True, 'removed': str(target)}
    else:
        raise ValueError('unknown filesystem operation')
    return {'ok': True, **info(target)}
