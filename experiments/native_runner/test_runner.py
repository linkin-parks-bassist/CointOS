"""Fault injection at durable model/tool boundaries; no production model required."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from experiments.native_runner import runner


def message(text=None, calls=None):
    return {'role': 'assistant', 'content': text, **({'tool_calls': calls} if calls else {})}


def write(ident='write'):
    return {'id': ident, 'type': 'function', 'function': {'name': 'write_file',
            'arguments': json.dumps({'name': 'result.txt', 'text': 'verified fixture\n'})}}


def events(path):
    with sqlite3.connect(path / 'session.sqlite3') as db:
        return [(kind, json.loads(payload)) for kind, payload in db.execute(
            'SELECT kind,payload FROM events ORDER BY id')]


def test_ack_is_durable_before_work_and_done_resume_uses_no_model(tmp_path):
    replies = iter([message('I will check.'), message(calls=[write()]), message('Result saved.')])
    observed = []
    def model(messages, tools):
        observed.append((messages.copy(), tools))
        if len(observed) > 1:
            assert events(tmp_path)[0][0] == 'acknowledgement'
        return next(replies)
    assert runner.run(tmp_path, 'Write the fixture', model)['phase'] == 'done'
    assert observed[0][1] == []
    assert observed[1][1] == runner.TOOLS
    assert (tmp_path / 'workspace/result.txt').read_text() == 'verified fixture\n'
    assert runner.run(tmp_path, None, lambda *args: pytest.fail('done session inferred again'))['phase'] == 'done'


def test_ack_cannot_execute_tools(tmp_path):
    with pytest.raises(ValueError, match='acknowledgement'):
        runner.run(tmp_path, 'write', lambda *args: message('checking', [write()]))
    assert not (tmp_path / 'workspace/result.txt').exists()


@pytest.mark.parametrize('boundary,expected', [('acknowledged', 'done'),
                                             ('model_recorded', 'done'),
                                             ('tool_started', 'ambiguous'),
                                             ('tool_effect', 'ambiguous'),
                                             ('tool_recorded', 'done')])
def test_actual_process_death_and_resume(tmp_path, boundary, expected):
    # os._exit bypasses Python finally/SQLite close to exercise committed state.
    code = '''
import os
from pathlib import Path
from experiments.native_runner import runner
from experiments.native_runner.test_runner import message, write
replies=iter([message('Checking now.'), message(calls=[write()]), message('saved')])
runner.run(Path(os.environ['PROBE_DIR']), 'write fixture', lambda *a: next(replies),
           lambda b: os._exit(77) if b == os.environ['PROBE_BOUNDARY'] else None)
'''
    import os
    result = subprocess.run([sys.executable, '-c', code], env={**os.environ,
        'PROBE_DIR': str(tmp_path), 'PROBE_BOUNDARY': boundary})
    assert result.returncode == 77
    if expected == 'ambiguous':
        before = (tmp_path / 'workspace/result.txt').read_bytes() if boundary == 'tool_effect' else None
        with pytest.raises(RuntimeError, match='ambiguous tool outcome'):
            runner.run(tmp_path, None, lambda *a: pytest.fail('reinferred uncertain action'))
        assert ((tmp_path / 'workspace/result.txt').read_bytes() if before is not None else None) == before
    else:
        replies = iter([message(calls=[write()]), message('saved')])
        def resume(messages, tools):
            if boundary == 'acknowledged':
                assert tools == runner.TOOLS
                return next(replies)
            assert messages[-1]['role'] == 'tool'
            return message('saved')
        assert runner.run(tmp_path, None, resume)['phase'] == 'done'
        results = [e for e in events(tmp_path) if e[0] == 'tool_result']
        assert len(results) == 1


def test_model_reasoning_not_retained_in_event_log(tmp_path):
    replies = iter([message('checking'), {**message('answer'), 'reasoning_content': 'private reasoning'}])
    runner.run(tmp_path, 'answer', lambda *a: next(replies))
    assert 'private reasoning' not in json.dumps(events(tmp_path))


def test_concurrent_owner_refused(tmp_path):
    import fcntl
    with (tmp_path / 'owner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            runner.run(tmp_path, 'new', lambda *a: pytest.fail('second owner inferred'))


@pytest.mark.parametrize('name', ['../outside', '/tmp/outside', '.', '..', 'sub/file'])
def test_path_escape_refused(tmp_path, name):
    item = write()
    item['function']['arguments'] = json.dumps({'name': name, 'text': 'no'})
    with pytest.raises(ValueError):
        runner.execute(tmp_path, item)


def test_symlink_refused_and_round_bound_survives_resume(tmp_path):
    (tmp_path / 'result.txt').symlink_to(tmp_path / 'elsewhere')
    with pytest.raises(ValueError, match='symlinks'):
        runner.execute(tmp_path, write())
    count = 0
    def loop(messages, tools):
        nonlocal count
        count += 1
        return message('ack') if not tools else message(calls=[write(str(count))])
    session = tmp_path / 'session'
    with pytest.raises(RuntimeError, match='exhausted'):
        runner.run(session, 'loop', loop)
    with pytest.raises(RuntimeError, match='exhausted'):
        runner.run(session, None, lambda *a: pytest.fail('budget reset on resume'))
