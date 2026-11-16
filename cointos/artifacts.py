"""Daemon-owned capture of an assignment's files. Git identities stay below this boundary."""
from __future__ import annotations

import contextlib
from copy import deepcopy
import fcntl
import hashlib
import os
from pathlib import Path
import shutil

from cointos import contracts, git, opencode, schema


def source_reference(source):
    return {'task': source['id'], 'version': source.get('record_version'), 'stage': source.get('stage'),
            'run': source.get('agent') or (source.get('receipt') or {}).get('run') or source.get('preserved_run')}


def material_key(reference):
    return hashlib.sha256(repr(sorted(reference.items())).encode()).hexdigest()


def remember_material(source, artifact):
    source.setdefault('material_snapshots', {})[material_key(source_reference(source))] = artifact


def carry(record, source):
    """Carry authored material through typed handoffs, never through copied workflow prose."""
    if record.get('done') or record.get('replaced_by'):
        return
    references = list(source.get('carried_work', []))
    if source.get('kind') in ('item', 'operator', 'breakdown', 'garden', 'tree-audit') and source.get('branch'):
        references.append(source_reference(source))
    references = [r for r in references if ('project' not in record or r['task'] != f"{record['project']}:{record['item']}")
                  and (record['kind'] == 'command' or record.get('stage') == r['stage'])
                  and ('project' not in record or r['task'].startswith(record['project'] + ':'))]
    for reference in references:
        if reference not in record.get('carried_work', []):
            record.setdefault('carried_work', []).append(dict(reference))
        from cointos import queues
        from cointos.state import L
        author = L['tasks'].get(reference['task']) or {}
        if record['kind'] != 'command' or author.get('kind') == 'breakdown':
            origin = L['queue'].get(author.get('record')) or {}
            record['depends'] = list(dict.fromkeys([*record['depends'],
                *(name for name in origin.get('depends', []) if name != record['item'])]))
            record['brief'] = queues.dependency_brief(record['brief'], record['depends'])


def compatible(source, task):
    if source.get('place') != task.get('place') or not source.get('branch') or not task.get('branch'):
        return False
    if source['kind'] == task['kind']:
        return source.get('stage') == task.get('stage')
    return source['kind'] in ('garden', 'tree-audit') and task['kind'] in ('garden', 'tree-audit')


def require_child_scope(brief, owner):
    """Child scope cannot be redirected to its managed author's private files."""
    if owner.get('branch') and any(value and value in brief
                                   for value in (owner.get('worktree'), owner.get('branch'))):
        raise ValueError('use relative file paths and behavioral obligations; '
                         'CointOS prepares files in each child\'s assigned workspace')


def carry_task(task, owner):
    """Recovery carries only work the new role is independently allowed to publish."""
    from cointos.state import L
    require_child_scope(task['brief'], owner)
    source = L['tasks'].get((owner.get('repair_origin') or {}).get('task'))
    from cointos import frontier
    record = frontier.record(source) if source else None
    if source and (frontier.origin(source) != owner['repair_origin'] or source.get('cancelled') or source.get('agent')
            or (record and (record.get('done') or record.get('replaced_by')
                            or record.get('held_by') not in (None, owner['id'])))
            or source.get('admission_hold') not in (None, 'repeated infrastructure launch failure')):
        raise ValueError('preserved work is held or its recovery authority changed; inspect the current assignment')
    inherited = [*owner.get('carried_work', []), *(L['queue'].get(owner.get('record')) or {}).get('carried_work', [])]
    if source:
        inherited += [*source.get('carried_work', []), source_reference(source)]
    references = []
    for reference in inherited:
        author = L['tasks'].get(reference['task'])
        if not author or author.get('record_version') != reference['version']:
            raise ValueError('preserved assignment authority changed; inspect the current handoff')
        if not compatible(author, task):
            continue
        if any(value and value in task['brief'] for value in (author.get('worktree'), author.get('branch'))):
            raise ValueError('use relative file paths; CointOS prepares preserved files in the new assignment')
        if reference not in references:
            references.append(dict(reference))
    if references:
        task['carried_work'] = references


def pending_material():
    """Material authority needed by unfinished queue and unqueued recovery assignments."""
    from cointos import tasks
    from cointos.state import L
    for record in L['queue'].values():
        if not record.get('done') and not record.get('replaced_by'):
            yield from record.get('carried_work', [])
    for task in L['tasks'].values():
        if (not task.get('record') and not task.get('cancelled') and not task.get('replaced_by')
                and (tasks.active(task) or ((task['status'] == 'failed'
                     or (task.get('receipt') or {}).get('disposition') == 'blocked') and not tasks.newer_attempt(task)))):
            yield from task.get('carried_work', [])


def carry_owner(record, owner):
    require_child_scope(record['brief'], owner)
    from cointos import queues
    from cointos.state import L
    origin = owner.get('repair_origin', {}).get('task')
    source = L['tasks'].get(origin) if origin else L['queue'].get(owner.get('record'))
    if source:
        candidate = deepcopy(record)
        carry(candidate, source)
        for reference in candidate.get('carried_work', []):
            author = L['tasks'].get(reference['task']) or {}
            if any(value and value in candidate['brief'] for value in (author.get('worktree'), author.get('branch'))):
                raise ValueError('use relative file paths and behavioral obligations; '
                                 'CointOS prepares files in each child\'s assigned workspace')
        if candidate != record:
            if queues.current(record) or record.get('proposed_by') not in (None, owner['id']):
                raise ValueError('existing work needs a checked replacement before inheriting other inputs; '
                                 'queue and planning handoff cannot change an existing assignment')
            record.update(candidate)


def materials(task, where):
    """Resolve retained source authority into immutable material before model launch."""
    from cointos.state import L, LOCK, save
    with LOCK:
        references = [*task.get('carried_work', []),
                      *(L['queue'].get(task.get('record')) or {}).get('carried_work', [])]
    found = []
    for reference in references:
        with LOCK:
            source = L['tasks'].get(reference['task'])
            if not source or source.get('record_version') != reference['version']:
                raise ValueError('preserved assignment authority changed; request a current handoff')
            if not compatible(source, task):
                if task['kind'] == 'item':
                    raise ValueError('preserved material belongs to a different work stage or scope')
                continue  # Planning records also carry construction inputs onward without importing them.
            key = material_key(reference)
            existing = source.get('material_snapshots', {}).get(key)
            producing_run = source.get('agent') or (source.get('receipt') or {}).get('run') or source.get('preserved_run')
            if existing is None and producing_run != reference['run']:
                raise ValueError('preserved author changed before capture; request a current handoff')
            snapshot = dict(source)
        if (existing is None and not snapshot.get('base_commit')
                and snapshot.get('retired') not in ('archived', 'landed', 'kept')
                and not Path(snapshot['worktree']).is_dir()):
            continue  # A refused prelaunch assignment has requirements, but no authored material.
        if existing is None:
            existing = preserved(snapshot, where)
            with LOCK:
                if (L['tasks'].get(source['id']) is not source
                        or source_reference(source) != reference):
                    raise ValueError('preserved assignment changed during preparation; retry its current handoff')
                source.setdefault('material_snapshots', {})[key] = existing
            save()
        if existing not in found:
            found.append(existing)
    return found


@contextlib.contextmanager
def ownership(task):
    """Serialize capture/preparation for one workspace, including concurrent lost-reply retries."""
    metadata = Path(git.run(task['worktree'], 'rev-parse', '--absolute-git-dir'))
    with (metadata / 'cointos-artifact.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('this workspace is being captured; retry after that operation finishes') from error
        yield


def capture(task, where, summary, *, preserve=False):
    """Preserve authored files as an immutable artifact; never ask the author to stage or commit.

    The caller owns the workspace and quiesces its producer. Stage checks precede index changes.
    Existing history is still checked by the submission/publication gates.
    """
    tree, rules = task['worktree'], where.get('test_policy')
    if git.run(tree, 'diff', '--name-only', '--diff-filter=U'):
        raise ValueError('workspace preparation is incomplete; preserve the files and report blocked')
    if rules and task['kind'] == 'item':
        forbidden = contracts.working_stage_changes(tree, task['stage'], rules)
        if forbidden:
            raise ValueError('files outside the assigned stage: ' + ', '.join(forbidden)
                             + '; preserve diagnostic work in scratch and keep the submitted files in scope')
    if schema.KINDS[task['kind']]['lands'] == 'merge':
        contracts.maintenance_history(where, task, git.head(where['path'], where['main_branch']),
                                      include_worktree=True, publication=not preserve)
    if not git.clean(tree):
        git.run(tree, 'add', '-A')
        # No synthetic empty changes: construction still needs a real changed artifact.
        if not git.ok(tree, 'diff', '--cached', '--quiet'):
            git.run(tree, 'commit', '-q', '-m', summary.strip() or 'Capture assigned work')
    return git.head(tree)


def capture_run(task, where, summary):
    # An already immutable artifact needs no producer pause. Final ownership/cleanliness
    # checks still revoke completion if the producer edits files after this observation.
    if git.clean(task['worktree']):
        return git.head(task['worktree'])
    with ownership(task), opencode.quiesce(task['agent']):
        return capture(task, where, summary)


def preserved(task, where):
    """Snapshot stopped work privately; leave its files, index and history untouched."""
    producing_run = source_reference(task)['run']
    if task.get('agent') or (producing_run and opencode.active(producing_run)):
        raise ValueError('the previous author is still stopping; retry preparation after it exits')
    tree, repo = Path(task['worktree']), where['path']
    if not tree.is_dir() and task.get('retired') in ('archived', 'landed', 'kept'):
        reference = (where['main_branch'] if task['retired'] == 'landed' else
                     git.ARCHIVE + task['branch'] if task['retired'] == 'archived' else task['branch'])
        return {'commit': git.head(repo, reference), 'base': task.get('base_commit') or git.head(repo, reference)}
    with ownership(task):
        start = git.head(tree)
        paths = contracts.working_paths(tree)
        def signature():
            result = []
            for name in paths:
                path = tree / name
                if not path.parent.resolve().is_relative_to(tree.resolve()):
                    raise ValueError('preserved source escapes its workspace: ' + name)
                if path.is_symlink():
                    value = ('link', os.readlink(path))
                elif path.is_file():
                    value = (path.stat().st_mode, hashlib.sha256(path.read_bytes()).hexdigest())
                elif path.exists():
                    raise ValueError('preserved source is not a regular file: ' + name)
                else:
                    value = ('absent',)
                result.append((name, value))
            return result
        before = signature()
        with contracts.checkout(repo, start) as prepared:
            for name in paths:
                source, destination = tree / name, Path(prepared) / name
                if not destination.parent.resolve().is_relative_to(Path(prepared).resolve()):
                    raise ValueError('prepared destination escapes its workspace: ' + name)
                if destination.is_symlink() or destination.is_file():
                    destination.unlink()
                elif destination.exists():
                    shutil.rmtree(destination)
                if source.exists() or source.is_symlink():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination, follow_symlinks=False)
            commit = capture({**task, 'worktree': str(prepared)}, where, 'Preserve unfinished assigned work', preserve=True)
            if git.head(tree) != start or contracts.working_paths(tree) != paths or signature() != before:
                raise ValueError('preserved files changed during preparation; retry without discarding them')
            git.run(repo, 'update-ref', 'refs/cointos/artifacts/' + commit, commit)
        return {'commit': commit, 'base': task.get('base_commit') or git.run(repo, 'merge-base', start, where['main_branch'])}


def prepare_assignment(task, where, material=()):
    """Give a not-yet-launched author current files, retaining unfinished work privately."""
    from cointos import landing
    from cointos.state import LOCK
    material = [artifact['commit'] for artifact in material]
    if task.get('preserved_run') and opencode.active(task['preserved_run']):
        raise ValueError('the previous author is still stopping; retry preparation after it exits')
    with ownership(task):
        main = git.head(where['path'], where['main_branch'])
        inputs = [*material, main]
        if task.get('stage') == 'test-contract':
            with LOCK:
                inputs += landing.tests_of(task)
        if all(git.contains(task['worktree'], artifact, 'HEAD') for artifact in inputs):
            return []
        captured = capture(task, where, 'Preserve assigned work before preparation', preserve=True)
        remaining = []
        with contracts.checkout(where['path'], captured) as prepared:
            for artifact in dict.fromkeys(inputs):
                if git.contains(prepared, artifact, 'HEAD'):
                    continue
                result = git.result(prepared, 'merge', '-q', '--no-edit', artifact)
                if result.returncode:
                    paths = [p for p in git.run(prepared, 'diff', '--name-only', '--diff-filter=U', '-z').split('\0') if p]
                    if not paths:
                        raise ValueError('file preparation failed; original work is preserved for recovery')
                    for name in paths:
                        entries = git.run(prepared, 'ls-files', '-u', '--', name)
                        side = '2' if artifact in material else '3'
                        choice = '--ours' if artifact in material else '--theirs'
                        if any(line.split('\t', 1)[0].split()[2] == side for line in entries.splitlines()):
                            git.run(prepared, 'checkout', choice, '--', name)
                            git.run(prepared, 'add', '--', name)
                        else:
                            git.run(prepared, 'rm', '-q', '-f', '--', name)
                    remaining += [p for p in paths if p not in remaining]
                    git.run(prepared, 'commit', '-q', '--no-edit')
            if git.head(task['worktree']) != captured or not git.clean(task['worktree']):
                raise ValueError('assigned files changed during preparation; preserve them and retry')
            git.run(task['worktree'], 'merge', '-q', '--ff-only', git.head(prepared))
    return remaining


def accept(task, worker, where, summary):
    message = summary + '\n\nWorker: ' + worker['receipt']['summary']
    with ownership(task), opencode.quiesce(task['agent']):
        capture(task, where, message)
        if git.run(task['worktree'], 'log', '-1', '--format=%B').strip() != message:
            git.run(task['worktree'], 'commit', '-q', '--allow-empty', '-m', message)
        return git.head(task['worktree'])


def prepare_review(task, worker, where):
    """Prepare privately, then advance only an unchanged clean review workspace.

    A composition failure never leaves markers or a half-prepared index in the agent's files.
    """
    tree, repo = task['worktree'], where['path']
    if not git.clean(tree):
        raise ValueError('review edits are present; accept or return the current work before preparing again')
    start = git.head(tree)
    main = git.head(repo, where['main_branch'])
    submitted = worker['receipt']['evidence']['commit']
    inputs = [main, *worker['receipt']['evidence'].get('tests', []), submitted]
    reconciliation = []
    with contracts.checkout(repo, start) as prepared:
        for artifact in dict.fromkeys(inputs):
            if git.contains(prepared, artifact, 'HEAD'):
                continue
            merged = git.result(prepared, 'merge', '-q', '--no-edit', artifact)
            if merged.returncode:
                paths = git.run(prepared, 'diff', '--name-only', '--diff-filter=U', '-z').split('\0')
                paths = [p for p in paths if p]
                rules = where.get('test_policy')
                if rules:
                    git.resolve_insertions(prepared, [p for p in paths if contracts.protected(p, rules)])
                unresolved = git.run(prepared, 'diff', '--name-only', '--diff-filter=U', '-z')
                if unresolved:
                    unresolved = [p for p in unresolved.split('\0') if p]
                    # Knowledge upkeep belongs to this reviewer. Prepare accepted definitions;
                    # the reviewer then edits ordinary files and explicitly reviews again.
                    if artifact == main and rules and all(contracts.matches(p, rules.get('non_code', []))
                                                         and not contracts.protected(p, rules) for p in unresolved):
                        for name in unresolved:
                            git.run(prepared, 'checkout', '--theirs', '--', name)
                            git.run(prepared, 'add', '--', name)
                        reconciliation.extend(unresolved)
                    else:
                        raise ValueError('accepted changes require behavioral reconciliation in: '
                                         + ', '.join(unresolved)
                                         + '. Original work is preserved; return the item with the incompatible requirements.')
                if not paths:
                    raise ValueError('candidate preparation failed; original work is preserved')
                git.run(prepared, 'commit', '-q', '--no-edit')
        candidate = git.head(prepared)
        if git.head(tree) != start or not git.clean(tree):
            raise ValueError('review files changed during preparation; no prepared files were installed')
        git.run(tree, 'merge', '-q', '--ff-only', candidate)
    return {'main': main, 'worker': submitted, 'candidate': candidate, 'reconcile': reconciliation}


def review(task, worker, where):
    with ownership(task), opencode.quiesce(task['agent']):
        capture(task, where, 'Preserve review edits')
        prepared = prepare_review(task, worker, where)
    result = {'summary': worker['receipt']['summary'],
                      'changes': '\n'.join(line for line in git.run(task['worktree'], 'diff',
                          prepared['main'], prepared['candidate']).splitlines()
                          if not line.startswith(('diff --git ', 'index '))),
                      'next_action': 'Inspect these changes and test the prepared files. Accept or return the work.'}
    if prepared['reconcile']:
        result['next_action'] = ('Current accepted definitions are prepared in ' + ', '.join(prepared['reconcile'])
                                 + '. Review these answers against the original concern, edit only where required, '
                                 'then call review again. '
                                 'Previous work is preserved; acceptance is blocked until that reconciliation.')
    scratch = opencode.run_dir(worker['receipt']['run']) / 'scratch'
    if scratch.is_dir():
        result['diagnostics'] = ('Worker diagnostic files are available through cointos_diagnostic. '
                                 'It copies selected sources into your own scratch. Replay against the prepared files; '
                                 'check assertions and exit status. Diagnostics are unverified.')
    return prepared, result


def diagnostic(task, worker, relative=None):
    """Transfer an inactive author's probe without exposing another checkout or its execution state."""
    with opencode.quiesce(task['agent']):
        return _diagnostic(task, worker, relative)


def _diagnostic(task, worker, relative):
    root = opencode.run_dir(worker['receipt']['run']) / 'scratch'
    if not root.is_dir():
        return {'files': []}
    if relative is None:
        return {'files': sorted(p.relative_to(root).as_posix() for p in root.rglob('*')
                                if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(root.resolve()))}
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('diagnostic path must name a file in the submitting run\'s scratch')
    source = root / path
    if source.is_symlink() or not source.resolve().is_relative_to(root.resolve()) or not source.is_file():
        raise ValueError('diagnostic source is not a retained regular scratch file')
    content = source.read_bytes()
    destination = opencode.run_dir(task['agent']) / 'scratch/worker-diagnostics' / path
    scratch = (opencode.run_dir(task['agent']) / 'scratch').resolve()
    if destination.is_symlink() or not destination.resolve().is_relative_to(scratch):
        raise ValueError('diagnostic destination must stay in this run\'s scratch')
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open('xb') as stream:
            stream.write(content)
    except FileExistsError:
        if destination.read_bytes() != content:
            raise ValueError('retained diagnostic changed; preserve the previously copied evidence')
    return {'path': str(destination), 'evidence': 'unverified diagnostic; replay and check assertions/exit status'}


def maintenance(task, where):
    """Capture scoped maintenance and compose accepted changes without exposing Git operations."""
    with ownership(task), opencode.quiesce(task['agent']):
        capture(task, where, 'Publish scoped maintenance')
        tree, repo = task['worktree'], where['path']
        main = git.head(repo, where['main_branch'])
        overlaps = []
        with contracts.checkout(repo, git.head(tree)) as prepared:
            result = git.result(prepared, 'merge', '-q', '--no-edit', main)
            if result.returncode:
                overlaps = [p for p in git.run(prepared, 'diff', '--name-only', '--diff-filter=U', '-z').split('\0') if p]
                if not overlaps:
                    raise ValueError('maintenance preparation failed; original work is preserved')
                for name in overlaps:
                    entries = git.run(prepared, 'ls-files', '-u', '--', name)
                    if any(line.split('\t', 1)[0].split()[2] == '3' for line in entries.splitlines()):
                        git.run(prepared, 'checkout', '--theirs', '--', name)
                        git.run(prepared, 'add', '--', name)
                    else:
                        git.run(prepared, 'rm', '-q', '-f', '--', name)
                git.run(prepared, 'commit', '-q', '--no-edit')
            git.run(tree, 'merge', '-q', '--ff-only', git.head(prepared))
        if overlaps:
            raise ValueError('your assigned files are prepared; verify the original concern in: '
                             + ', '.join(overlaps) + '. Edit only where required, then retry. '
                             'Previous work is preserved. Nothing was published.')
        return git.head(tree)
