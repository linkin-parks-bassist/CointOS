"""Disposable native harness apparatus; no daemon imports or production installation.

Run: python3 experiments/native_runner/runner.py SESSION_DIR --prompt '...'
Resume: same command without --prompt. Events are JSONL on stdout and durable in SQLite.
Only flat, non-symlink files inside SESSION_DIR/workspace are exposed to the model.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
import time
import urllib.request


def tool(name, description, properties, required):
    return {'type': 'function', 'function': {'name': name, 'description': description,
        'parameters': {'type': 'object', 'properties': properties, 'required': required,
                       'additionalProperties': False}}}


TOOLS = [tool('read_file', 'Read a sandbox file, at most 16 KiB.',
              {'name': {'type': 'string'}}, ['name']),
         tool('write_file', 'Write a sandbox file, at most 16 KiB.',
              {'name': {'type': 'string'}, 'text': {'type': 'string'}}, ['name', 'text'])]
SYSTEM = ('You are an experimental coding assistant working only in a disposable workspace. '
          'Use the supplied tools; never invent tool results. Read back written files before '
          'claiming success. Do not claim tests or production deployment. Finish with a concise answer.')


def persist(db, state, kind, payload):
    """The state transition and its observable event commit together."""
    with db:
        db.execute('UPDATE state SET body=? WHERE id=1', (json.dumps(state),))
        db.execute('INSERT INTO events(at,kind,payload) VALUES(?,?,?)',
                   (time.time(), kind, json.dumps(payload)))


def execute(workspace, call):
    fn = call['function']
    args = json.loads(fn['arguments'])
    if not isinstance(args, dict):
        raise ValueError('tool arguments must be an object')
    name = args.get('name')
    if (not isinstance(name, str) or not name or name in ('.', '..')
            or '/' in name or '\\' in name):
        raise ValueError('use one flat sandbox filename')
    path = workspace / name
    if path.is_symlink():
        raise ValueError('symlinks are not sandbox files')
    if fn['name'] == 'read_file':
        with path.open('rb') as stream:
            data = stream.read(16385)
        if len(data) > 16384:
            raise ValueError('file exceeds 16 KiB')
        return {'text': data.decode()}
    if fn['name'] != 'write_file' or not isinstance(args.get('text'), str):
        raise ValueError('unknown tool or invalid arguments')
    data = args['text'].encode()
    if len(data) > 16384:
        raise ValueError('write exceeds 16 KiB')
    fd, temporary = tempfile.mkstemp(dir=workspace, prefix='.write-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {'bytes': len(data)}


def advance(db, state, workspace, model, checkpoint):
    """model(messages, tools) returns a complete assistant message; checkpoint injects crashes."""
    if state['phase'] == 'ack':
        response = model(state['messages'] + [{'role': 'user', 'content':
            'Acknowledge that you are starting the already authorised request in one short sentence. '
            'Do not claim completed work, ask for permission, or wait for another go-ahead. '
            'The next phase will execute the work automatically.'}], [])
        text = response.get('content')
        if response.get('tool_calls') or not isinstance(text, str) or not text.strip():
            raise ValueError('acknowledgement must be nonempty model text without tool calls')
        state['messages'].append({'role': 'assistant', 'content': text})
        state['phase'] = 'work'
        persist(db, state, 'acknowledgement', {'text': text})
        checkpoint('acknowledged')
    while state['phase'] == 'work':
        if state['pending']:
            call = state['pending'][0]
            if state['effect'] == 'started':
                raise RuntimeError('ambiguous tool outcome: inspect workspace and journal; automatic replay refused')
            state['effect'] = 'started'
            persist(db, state, 'tool_started', {'call': call})
            checkpoint('tool_started')
            try:
                result = {'ok': True, **execute(workspace, call)}
            except (OSError, ValueError, TypeError, KeyError) as error:
                result = {'ok': False, 'error': str(error)}
            checkpoint('tool_effect')
            state['messages'].append({'role': 'tool', 'tool_call_id': call['id'],
                                      'content': json.dumps(result)})
            state['pending'].pop(0)
            state['effect'] = None
            persist(db, state, 'tool_result', {'id': call['id'], 'result': result})
            checkpoint('tool_recorded')
            continue
        if state['rounds'] >= 8:
            raise RuntimeError('eight work rounds exhausted; session retained')
        # Charge attempts before inference: repeated interruption cannot reset the bound.
        state['rounds'] += 1
        persist(db, state, 'model_requested', {'round': state['rounds']})
        raw = model(state['messages'], TOOLS)
        response = {k: v for k, v in raw.items() if k in ('role', 'content', 'tool_calls')}
        calls = response.get('tool_calls') or []
        if len(calls) > 8 or any(not isinstance(c.get('id'), str) or not c['id']
                                 or not isinstance(c.get('function'), dict) for c in calls):
            raise ValueError('malformed or oversized tool batch')
        ids = [c['id'] for c in calls]
        previous = {c['id'] for m in state['messages'] for c in m.get('tool_calls', [])}
        if len(set(ids)) != len(ids) or previous.intersection(ids):
            raise ValueError('tool call IDs must be unique across this session')
        state['messages'].append({k: v for k, v in response.items()
                                  if k in ('role', 'content', 'tool_calls')})
        state['pending'] = calls
        if not calls:
            if not isinstance(response.get('content'), str) or not response['content'].strip():
                raise ValueError('empty final response')
            state['phase'] = 'done'
        persist(db, state, 'model_response', {'message': response, 'phase': state['phase']})
        checkpoint('model_recorded')


def run(directory, prompt, model, checkpoint=lambda boundary: None):
    directory = Path(directory).resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (directory / 'owner.lock').open('a') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        workspace = directory / 'workspace'
        if workspace.is_symlink():
            raise ValueError('workspace must not be a symlink')
        workspace.mkdir(mode=0o700, exist_ok=True)
        db = sqlite3.connect(directory / 'session.sqlite3')
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY, body TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, at REAL, kind TEXT, payload TEXT)')
            row = db.execute('SELECT body FROM state WHERE id=1').fetchone()
            if row:
                if prompt is not None:
                    raise ValueError('existing session: resume without --prompt')
                state = json.loads(row[0])
            else:
                if not prompt:
                    raise ValueError('new session needs --prompt')
                state = {'phase': 'ack', 'rounds': 0, 'pending': [], 'effect': None,
                         'messages': [{'role': 'system', 'content': SYSTEM},
                                      {'role': 'user', 'content': prompt}]}
                with db:
                    db.execute('INSERT INTO state VALUES(1,?)', (json.dumps(state),))
            advance(db, state, workspace, model, checkpoint)
            return state
        finally:
            db.close()


def gateway(url, model_name, max_tokens, timeout, request_class='background'):
    """An unissued key is an ordinary user request, demoted to background priority.

    Never borrow Coin/agent credentials. The live gateway currently shares the user
    cache identity, so this is for short isolated probes, not parallel throughput.
    """
    token = secrets.token_urlsafe(24)
    def complete(messages, tools):
        body = {'model': model_name, 'messages': messages, 'stream': False,
                'max_tokens': max_tokens, 'reasoning_effort': 'low', 'request_class': request_class}
        if tools:
            body['tools'] = tools
        request = urllib.request.Request(url.rstrip('/') + '/chat/completions', json.dumps(body).encode(),
            {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)['choices'][0]['message']
    return complete


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--prompt')
    parser.add_argument('--url', default='http://127.0.0.1:4200/v1')
    parser.add_argument('--model', default='default')
    parser.add_argument('--max-tokens', type=int, default=768)
    parser.add_argument('--timeout', type=float, default=180)
    parser.add_argument('--request-class', choices=('background', 'user'), default='background')
    args = parser.parse_args()
    start = time.monotonic()
    emitted = 0
    def progress(boundary):
        nonlocal emitted
        with sqlite3.connect(args.directory / 'session.sqlite3') as db:
            rows = db.execute('SELECT * FROM events WHERE id>? ORDER BY id', (emitted,)).fetchall()
        for seq, at, kind, payload in rows:
            print(json.dumps({'seq': seq, 'at': at, 'kind': kind, 'payload': json.loads(payload),
                              'elapsed': time.monotonic() - start}), flush=True)
            emitted = seq
    run(args.directory, args.prompt, gateway(args.url, args.model, args.max_tokens, args.timeout,
                                           args.request_class), progress)
    progress('finished')


if __name__ == '__main__':
    main()
