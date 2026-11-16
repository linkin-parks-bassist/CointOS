"""Coordinators read selected sessions through daemon authority, across private-store migration."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from cointos import api, cli, state, transcript
from tests import support


def database(path, sessions):
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.executescript('create table message(id,session_id,data); create table part(id,message_id,session_id,data);')
    for session, words in sessions.items():
        message = 'message-' + session
        connection.execute('insert into message values(?,?,?)', (message, session, json.dumps({'role': 'assistant'})))
        if words:
            connection.execute('insert into part values(?,?,?,?)', ('part-' + session, message, session,
                                                                   json.dumps({'type': 'text', 'text': words})))
    connection.commit()
    connection.close()
    return path


class TraceSources(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.current = self.root / 'private'
        self.db = database(self.current / 'data/opencode/opencode.db', {'current': 'New authoritative progress.'})
        self.legacy = database(self.root / 'legacy.db', {'old': 'Original retained evidence.', 'current': 'STALE duplicate.'})
        self.enterContext(patch.object(transcript, 'database', return_value=self.legacy))
        self.agents = self.root / 'agents'
        self.agents.mkdir()
        self.task = {'id': 'p:work', 'role': 'worker', 'session': 'current', 'session_store': str(self.current),
                     'previous_sessions': ['old']}

    def test_private_current_and_legacy_history_are_combined_without_duplicate_or_stale_rows(self):
        shown = transcript.read_task(self.task, self.agents, show='1-9')['text']
        self.assertIn('Original retained evidence.', shown)
        self.assertIn('New authoritative progress.', shown)
        self.assertNotIn('STALE', shown)
        self.assertLess(shown.index('Original retained'), shown.index('New authoritative'))
        exported = transcript.read_task(self.task, self.agents, export=True)
        self.assertEqual(exported['messages'], 2)
        self.assertNotIn('STALE', exported['text'])

    def test_missing_private_current_store_never_falls_back_to_stale_global_history(self):
        self.db.unlink()
        with self.assertRaisesRegex(ValueError, 'current trace store is unavailable'):
            transcript.read_task(self.task, self.agents)

    def test_current_run_metadata_restores_store_authority_and_dict_task_sessions(self):
        self.task.pop('session_store')
        self.task['agent'] = 'active'
        run = self.agents / 'active'
        run.mkdir()
        (run / 'run.json').write_text(json.dumps({'task': {'id': 'p:work', 'worktree': '/unused'},
                                                'session': 'current', 'agent_data': str(self.current)}))
        other = self.agents / 'other'
        other.mkdir()
        (other / 'run.json').write_text(json.dumps({'task': {'id': 'p:other'}, 'session': 'private-other'}))
        self.assertEqual(transcript.sessions_of(self.task, self.agents), ['old', 'current'])
        self.assertNotIn('STALE', transcript.read_task(self.task, self.agents, show='1-9')['text'])

    def test_empty_assistants_keep_turn_offsets_across_stores(self):
        missing = self.root / 'empty.db'
        database(missing, {'empty': ''})
        found = transcript.entries({'empty': missing, 'current': self.db}, ['empty', 'current'])
        self.assertEqual(found[0]['turn'], 2)

    def test_unavailable_historical_coverage_is_reported(self):
        self.task['previous_sessions'] = ['unavailable']
        self.assertIn('Historical coverage incomplete', transcript.read_task(self.task, self.agents)['text'])

    def test_proxy_reads_outside_lock_and_refuses_worker_peer_or_user_conversation_access(self):
        project = support.project(self, support.repository(self))
        worker = support.running(support.queued(project, 'source'), 'worker', worktree=False)
        manager = support.running(support.queued(project, 'manager', 'Coordinate', kind='command'), 'manager', worktree=False)
        def read(task, agents, **options):
            self.assertFalse(state.LOCK._is_owned())
            self.assertTrue(options['public'])
            return {'text': 'selected evidence'}
        with patch.object(transcript, 'read_task', side_effect=read):
            result = api.dispatch('read-log', {'caller': support.caller(manager, 'manager'), 'task': worker['id']})
            self.assertEqual(result['text'], 'selected evidence')
            self.assertEqual(api.dispatch('read-log', {'caller': support.caller(worker, 'worker'), 'task': worker['id']})['text'], 'selected evidence')
            with self.assertRaisesRegex(ValueError, 'workers inspect their own'):
                api.dispatch('read-log', {'caller': support.caller(worker, 'worker'), 'task': manager['id']})
            with self.assertRaisesRegex(ValueError, 'user conversation'):
                api.dispatch('read-log', {'caller': support.caller(manager, 'manager'), 'task': 'coin'})

    def test_managed_cli_never_opens_peer_databases_or_run_directories(self):
        args = argparse.Namespace(task='p:work', show=None, kind=None, turn=None, grep=None, last=40)
        with patch.dict(os.environ, {'COINTOS_AGENT': 'coordinator'}), \
             patch.object(cli, 'call', return_value={'text': 'remote evidence', 'messages': 2, 'sessions': 2}) as call, \
             patch.object(cli, 'ledger', return_value={'tasks': {'p:work': self.task}}), \
             patch.object(transcript, 'task_sources', side_effect=AssertionError('local peer read')), \
             patch.object(transcript, 'sessions_of', side_effect=AssertionError('local run scan')):
            self.assertEqual(cli.read_log(args), 'remote evidence')
            out = self.root / 'export.txt'
            cli.write_transcript('p:work', str(out))
            self.assertEqual(out.read_text(), 'remote evidence')
            self.assertTrue(all(c.args[0] == 'read-log' for c in call.call_args_list))
