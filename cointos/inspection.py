"""Source observations for coordinators, without exposing storage or editor workspaces."""
from __future__ import annotations

import contextlib
import itertools
import os
import stat
import shutil
import tempfile
from pathlib import Path

from cointos import artifacts, contracts, git


def prepare(task, where, source=None):
    """Prepare executable diagnostic files without editor drafts or storage metadata."""
    from cointos import opencode
    scratch = opencode.run_dir(task['agent']) / 'scratch'
    if not scratch.is_dir() or scratch.is_symlink():
        raise ValueError('this run has no owned diagnostic scratch directory')
    destination = Path(tempfile.mkdtemp(prefix=where['name'] + '-', dir=scratch))
    try:
        reference = (artifacts.preserved(source, where)['commit'] if source else
                     git.head(where['path'], where['main_branch']))
        with contracts.checkout(where['path'], reference) as prepared:
            def ignore(directory, names):
                relative = Path(directory).relative_to(prepared)
                return [name for name in names if excluded(relative / name, where)]
            shutil.copytree(prepared, destination, dirs_exist_ok=True, symlinks=True, ignore=ignore)
    except Exception:
        shutil.rmtree(destination)
        raise
    from cointos.state import log
    log('diagnostic source prepared', task=task['id'], run=task['agent'], project=where['name'],
        commit=reference, directory=str(destination))
    return {'project': where['name'], 'directory': str(destination),
            'note': ('Retained assignment files' if source else 'Accepted project files') +
                    ' are prepared for local diagnostic commands. Editor drafts are excluded.'}


def excluded(path, where):
    parts = Path(path).parts
    if any(part in ('.git', '.hg', '.svn', '.knowledge') for part in parts):
        return True
    tree = Path(where.get('tree', '.knowledge'))
    if tree.is_absolute():
        try:
            tree = tree.relative_to(where['path'])
        except ValueError:
            return False
    return parts[:len(tree.parts)] == tree.parts


def relative(path, where):
    value = Path(path)
    if value.is_absolute() or '..' in value.parts:
        raise ValueError('source paths must stay relative to the assigned project')
    if excluded(value, where):
        raise ValueError('use knowledge-tree tools for maintained answers; private storage is not a source file')
    return value


def open_text(root, selected, where, stack):
    """Resolve contained aliases, then open each component without following replacement links."""
    root = root.resolve()
    target = (root / selected).resolve()
    if not target.is_relative_to(root) or excluded(target.relative_to(root), where):
        raise ValueError('source links must stay inside the assigned source and outside private storage')
    parts = target.relative_to(root).parts
    if not parts:
        raise ValueError('name a source file')
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    directory = os.open(root, flags | os.O_DIRECTORY)
    stack.callback(os.close, directory)
    for part in parts[:-1]:
        directory = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
        stack.callback(os.close, directory)
    descriptor = os.open(parts[-1], flags, dir_fd=directory)
    stream = stack.enter_context(os.fdopen(descriptor, encoding='utf-8'))
    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
        raise ValueError('name a regular text source file')
    return stream


def files(task, where, *, limit, path=None, start=1):
    """Read live assigned files or immutable accepted/project material. Caller holds no ledger lock."""
    if type(start) is not int or start < 1 or type(limit) is not int or limit < 1:
        raise ValueError('start and limit must be positive integers')
    tree = Path(task['worktree']) if task and task.get('worktree') else None
    live = bool(tree and tree.is_dir())
    if task and not task.get('branch'):
        raise ValueError('use a project or construction task for source; runtime state has task/status/log tools')
    if live:
        reference = None
        base = task.get('base_commit') or git.run(tree, 'merge-base', 'HEAD', where['main_branch'])
        names = contracts.working_paths(tree, base)
    else:
        if task:
            saved = task.get('material_snapshots', {}).get(artifacts.material_key(artifacts.source_reference(task)))
            reference = (saved or {}).get('commit') or (task.get('receipt') or {}).get('evidence', {}).get('commit')
            if not reference and task.get('retired') == 'archived':
                reference = git.ARCHIVE + task['branch']
            if not reference:
                raise ValueError('this task has no retained source view; inspect the accepted project and task receipt')
            names = git.changed(where['path'], task.get('base_commit') or reference, reference)
        else:
            reference = git.head(where['path'], where['main_branch'])
            names = git.run(where['path'], 'ls-tree', '-r', '--name-only', '-z', reference).split('\0')
    names = sorted(name for name in names if name and not excluded(name, where))
    selected = relative(path, where) if path else None
    if selected is None or str(path).endswith('/'):
        if selected:
            names = [name for name in names if name.startswith(selected.as_posix().rstrip('/') + '/')]
        page = names[start - 1:start - 1 + limit]
        return {'files': page, 'next': start + len(page) if start - 1 + len(page) < len(names) else None}
    with contextlib.ExitStack() as stack:
        root = tree if live else stack.enter_context(contracts.checkout(where['path'], reference))
        try:
            stream = open_text(root, selected, where, stack)
            lines = list(itertools.islice(stream, start - 1, start - 1 + limit + 1))
        except UnicodeError as error:
            raise ValueError('this is not a UTF-8 text source; use a scoped diagnostic task for binary inspection') from error
        except OSError as error:
            raise ValueError('this source file is unavailable; refresh the task view and retry') from error
        return {'path': selected.as_posix(), 'start': start, 'lines': [line.rstrip('\n') for line in lines[:limit]],
                'next': start + limit if len(lines) > limit else None}
