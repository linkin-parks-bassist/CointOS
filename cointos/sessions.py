"""Move one retained conversation into its assignment's private OpenCode store, without resetting it."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from cointos.config import STATE, read_owned_json, write_json


def environment(directory, store, catalog):
    env = {**os.environ, 'OPENCODE_CONFIG': str(directory / 'opencode.json'),
           'OPENCODE_MODELS_PATH': str(catalog), 'OPENCODE_DISABLE_MODELS_FETCH': '1',
           'OPENCODE_DISABLE_DEFAULT_PLUGINS': '1'}
    if store is not None:
        env.update({name: str(store / child) for name, child in (
            ('XDG_DATA_HOME', 'data'), ('XDG_STATE_HOME', 'state'),
            ('XDG_CONFIG_HOME', 'config'), ('XDG_CACHE_HOME', 'cache'))})
    return env


def export(executable, session, directory, env, destination, timeout):
    """Capture to a regular file: pipe-based CLI exports can truncate while exiting successfully."""
    import sqlite3
    from cointos import transcript
    database = Path(env.get('XDG_DATA_HOME') or Path.home() / '.local/share') / 'opencode/opencode.db'
    if database.is_file():
        try:
            with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as connection:
                if transcript.native_v2(connection):
                    raise ValueError('retained V2 history requires the native adapter; no V1 client was started')
        except sqlite3.Error as error:
            raise ValueError('retained session storage is unreadable; preserve it before export') from error
    with destination.open('xb') as output:
        result = subprocess.run([executable, 'export', '--pure', session], cwd=directory, env=env,
                                stdout=output, stderr=subprocess.PIPE, timeout=timeout)
    if destination.stat().st_size == 0 and b'Session not found:' in result.stderr:
        return None
    if result.returncode:
        raise ValueError('retained session export failed; original and private stores are preserved')
    try:
        value = read_owned_json(destination)
    except (OSError, ValueError) as error:
        raise ValueError('retained session export is incomplete; source history is preserved') from error
    if (not isinstance(value, dict) or not isinstance(value.get('info'), dict)
            or value['info'].get('id') != session or not isinstance(value.get('messages'), list)):
        raise ValueError('retained session export does not identify the assigned conversation')
    return value


def equivalent(source, target):
    # Native import changes only the containing project's identity/path when a Git
    # checkout becomes an ordinary directory. Conversation identity/content must not change.
    def info(value):
        return {k: v for k, v in value['info'].items() if k not in ('projectID', 'path')}
    return info(source) == info(target) and source['messages'] == target['messages']


def prepare(task, directory, store, executable, timeout, namespace='session-migrations'):
    session = task.get('session')
    if not session:
        return
    store, directory = Path(store), Path(directory)
    migration = (STATE / namespace / hashlib.sha256(task['id'].encode()).hexdigest()
                 / hashlib.sha256(session.encode()).hexdigest())
    migration.mkdir(parents=True, exist_ok=True, mode=0o700)
    receipt_path, archive = migration / 'receipt.json', migration / 'source.json'
    receipt = read_owned_json(receipt_path, None)
    if receipt is not None and (not isinstance(receipt, dict)
                                or set(receipt) != {'session', 'store', 'source_digest'}
                                or receipt.get('session') != session or receipt.get('store') != str(store)
                                or not isinstance(receipt.get('source_digest'), str)
                                or len(receipt['source_digest']) != 64
                                or any(c not in '0123456789abcdef' for c in receipt['source_digest'])):
        raise ValueError('retained session migration ownership is invalid; preserve both stores')
    target_env = environment(directory, store, store / 'models.json')
    with tempfile.TemporaryDirectory(prefix='verify-', dir=migration) as temporary:
        target = export(executable, session, task['worktree'], target_env, Path(temporary) / 'target.json', timeout)
        if target is not None:
            if receipt is not None or task.get('session_store') == str(store):
                return  # A previously verified/private conversation may legitimately have advanced.
            source = read_owned_json(archive, None)
            if source is None or not equivalent(source, target):
                raise ValueError('private session has unverified existing history; preserve it for reconciliation')
        elif receipt is not None or task.get('session_store') == str(store):
            raise ValueError('private retained session is missing; preserve its newer history for recovery')
        else:
            if not archive.exists():
                origin = Path(task['session_store']) if task.get('session_store') else None
                original_env = environment(directory, origin, store / 'models.json')
                captured = Path(temporary) / 'source.json'
                source = export(executable, session, task['worktree'], original_env, captured, timeout)
                if source is None:
                    raise ValueError('assigned retained session is unavailable; no replacement conversation was created')
                os.replace(captured, archive)
            else:
                source = read_owned_json(archive)
            result = subprocess.run([executable, 'import', '--pure', str(archive)], cwd=task['worktree'],
                                    env=target_env, capture_output=True, timeout=timeout)
            if result.returncode:
                raise ValueError('retained session import failed; source export and private store are preserved')
            target = export(executable, session, task['worktree'], target_env,
                            Path(temporary) / 'imported.json', timeout)
            if target is None or not equivalent(source, target):
                raise ValueError('retained session import changed conversation data; no agent was started')
    digest = hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    write_json(receipt_path, {'session': session, 'store': str(store), 'source_digest': digest})


def verify_v2(source, target):
    """Check the semantic identity retained by the native V1 database converter.

    The native converter flattens parts and replaces internal message/part storage;
    user identity, text and time and completed tool effects must survive intact.
    Unrecognised content fails closed rather than silently losing context.
    """
    if source['info']['id'] != target['info']['id']:
        raise ValueError('OpenCode 2 changed retained session identity')
    current = {m['id']: m for m in target['messages']}
    for old in source['messages']:
        info, parts = old['info'], old['parts']
        new = current.get(info['id'])
        # V1 synthetic compaction users become native compaction records.
        if any(p['type'] == 'compaction' for p in parts) or info.get('summary') is True:
            summaries = [m for m in target['messages'] if m['type'] == 'compaction']
            if not summaries:
                raise ValueError('OpenCode 2 omitted compaction context')
            if info.get('summary') is True and any(not any(p['text'] in m.get('summary', '') for m in summaries)
                                           for p in parts if p['type'] == 'text'):
                raise ValueError('OpenCode 2 changed retained compaction summary')
            continue
        if new is None or new['type'] != info['role']:
            raise ValueError('OpenCode 2 omitted a retained message')
        if info['role'] == 'user':
            if new['time']['created'] != info['time']['created']:
                raise ValueError('OpenCode 2 changed original user time')
            if new['text'] != '\n'.join(p['text'] for p in parts if p['type'] == 'text'):
                raise ValueError('OpenCode 2 changed original user text')
            if any(p['type'] not in ('text', 'step-start', 'step-finish') for p in parts):
                raise ValueError('OpenCode 2 attachment migration needs explicit verification')
            continue
        content = new.get('content', [])
        for p in parts:
            if p['type'] in ('step-start', 'step-finish', 'snapshot', 'patch'):
                continue
            if p['type'] in ('text', 'reasoning'):
                if not any(c['type'] == p['type'] and c['text'] == p['text'] for c in content):
                    raise ValueError('OpenCode 2 omitted retained assistant context')
            elif p['type'] == 'tool':
                c = next((c for c in content if c['type'] == 'tool' and c['id'] == p['callID']), None)
                if c is None or c['name'] != p['tool'] or c['state']['status'] != p['state']['status']:
                    raise ValueError('OpenCode 2 changed a retained tool call')
                if c['state'].get('input') != p['state'].get('input'):
                    raise ValueError('OpenCode 2 changed retained tool arguments')
                if p['state']['status'] == 'completed':
                    text = '\n'.join(v.get('text', '') for v in c['state'].get('content', []))
                    if text != p['state']['output']:
                        raise ValueError('OpenCode 2 changed a completed tool result')
                    for attachment in p['state'].get('attachments', []):
                        if not any(v.get('type') == 'file' and v.get('uri') == attachment.get('url')
                                   and v.get('mime') == attachment.get('mime') for v in c['state'].get('content', [])):
                            raise ValueError('OpenCode 2 omitted a retained tool attachment')
            else:
                raise ValueError('OpenCode 2 message migration needs explicit verification')


def prepare_v2(task, directory, store, executable, legacy, timeout):
    """Convert a private copy of just this assignment, keeping the V1 store intact."""
    import sqlite3
    import secrets
    import time
    from cointos import opencode, opencode2

    if not task.get('session'):
        return
    directory, store = Path(directory), Path(store)
    migration = (STATE / 'session-migrations-v2' / hashlib.sha256(task['id'].encode()).hexdigest()
                 / hashlib.sha256(task['session'].encode()).hexdigest())
    migration.mkdir(parents=True, exist_ok=True, mode=0o700)
    receipt, archive = migration / 'receipt.json', migration / 'source-v1.json'
    expected = {'session': task['session'], 'store': str(store)}
    retained_receipt = read_owned_json(receipt, None)
    if retained_receipt is not None:
        source = read_owned_json(archive)
        digest = hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if retained_receipt != {**expected, 'source_digest': digest}:
            raise ValueError('OpenCode 2 session migration ownership is invalid')
    origin = Path(task['session_store']) if task.get('session_store') else None
    if retained_receipt is not None or origin == store:
        native_snapshot(store, task['session'], task['worktree'])
        return  # Reading a native store must not start its job scheduler or execute work.
    metadata = directory / 'migration'
    metadata.mkdir(mode=0o700)
    config = {'plugin': [str(opencode.ROOT / 'cointos/opencode_migration_plugin')], 'mcp': {},
              'autoupdate': False, 'share': 'disabled', 'compaction': {'auto': False}}
    write_json(metadata / 'opencode.json', config, mode=0o600)
    if not receipt.exists() and origin != store:
        stage = store.parent / 'v1-import'
        stage.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_json(stage / 'models.json', {})
        prepare(task, metadata, stage, legacy, timeout, namespace='session-migrations-v2-source')
        database = store / 'data/opencode/opencode.db'
        if not database.exists():
            database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with sqlite3.connect('file:' + str(stage / 'data/opencode/opencode.db') + '?mode=ro', uri=True) as source:
                with sqlite3.connect(database) as target:
                    source.backup(target)
        with tempfile.TemporaryDirectory(dir=metadata) as temp:
            source = export(legacy, task['session'], task['worktree'],
                            environment(metadata, stage, stage / 'models.json'), Path(temp) / 'source.json', timeout)
            if not archive.exists():
                write_json(archive, source, mode=0o600)
    # A previously converted but not yet receipted store also needs no execution.
    from cointos import transcript
    with sqlite3.connect('file:' + str(database) + '?mode=ro', uri=True) as existing:
        converted = transcript.native_v2(existing)
        if not converted and existing.execute("select 1 from sqlite_master where name='job'").fetchone():
            raise ValueError('unqualified legacy job storage; preserve it before conversion')
    if converted:
        target = native_snapshot(store, task['session'], task['worktree'])
        source = read_owned_json(archive)
        verify_v2(source, target)
        digest = hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        write_json(receipt, {**expected, 'source_digest': digest}, mode=0o600)
        return
    env = environment(metadata, store, store / 'models.json')
    env.update(COINTOS_OPENCODE_BINARY=executable, COINTOS_OPENCODE_V2='1', PWD=str(metadata),
               OPENCODE_PASSWORD=secrets.token_urlsafe(32))
    # Conversion needs no project execution. Do not load worktree-local plugins
    # in the daemon's unconfined migration preparation process.
    server, url = opencode.start_server(metadata, str(metadata), env)
    token = opencode2.AUTH.set(env['OPENCODE_PASSWORD'])
    try:
        deadline = time.monotonic() + timeout
        while True:
            status = opencode2.request(url, 'experimental/migration/v1')
            if status['status'] == 'completed':
                break
            if status['status'] == 'error' or time.monotonic() >= deadline:
                raise ValueError('OpenCode 2 native migration did not complete; V1 history is preserved')
            time.sleep(.2)
        target = opencode2.request(url, 'experimental/' + opencode2.path(task['session'], 'export'))['data']
        if Path(target['info']['location']['directory']).resolve() != Path(task['worktree']).resolve():
            raise ValueError('OpenCode 2 changed retained session directory')
        if not receipt.exists() and origin != store:
            source = read_owned_json(archive)
            verify_v2(source, target)
            digest = hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            write_json(receipt, {**expected, 'source_digest': digest}, mode=0o600)
    finally:
        opencode2.AUTH.reset(token)
        opencode.stop_group(server.pid)
        server.wait()


def native_snapshot(store, session, worktree):
    import sqlite3
    from cointos import transcript
    database = Path(store) / 'data/opencode/opencode.db'
    try:
        with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as connection:
            connection.execute('begin')
            row = connection.execute('select directory from session_v2 where id=?', (session,)).fetchone()
            if row is None or Path(row[0]).resolve() != Path(worktree).resolve():
                raise ValueError('native retained session or directory is unavailable')
            return {'info': {'id': session, 'location': {'directory': row[0]}},
                    'messages': list(transcript.native_messages(connection, session))}
    except sqlite3.Error as error:
        raise ValueError('native retained session store is unreadable; preserve its history') from error
