"""Diagnostic storage must not freeze model progress or control transactions."""
import contextlib
import http.client
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from cointos import daemon, gateway, journal, state
from tests import support


class Journal(unittest.TestCase):
    def setUp(self):
        journal.flush()
        support.fresh_ledger(self)
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(journal, 'STATE', self.root))
        self.enterContext(patch.object(state.configuration, 'LEDGER', self.root / 'cointos.json'))

    def test_staging_freezes_payload_and_destination_without_file_io(self):
        event = {'event': 'evidence', 'details': {'files': ['original']}, 'prompt': 'private'}
        journal.write(event, 8192)
        event['details']['files'].append('later')
        self.assertFalse((self.root / 'events.jsonl').exists())
        with patch.object(journal, 'STATE', self.root / 'other'):
            journal.flush()
        record = json.loads((self.root / 'events.jsonl').read_text())
        self.assertEqual(record['details']['files'], ['original'])
        self.assertNotIn('prompt', record)
        self.assertFalse((self.root / 'other').exists())

    def test_blocked_journal_fifo_allows_tcp_reads_and_another_producer(self):
        path = self.root / 'events.jsonl'
        os.mkfifo(path)
        entered, first_staged, second_staged = (threading.Event() for _ in range(3))
        errors = []
        real_append = journal._append
        def append(*args):
            entered.set()
            real_append(*args)  # FIFO open blocks until the test supplies a reader
        def producer(name, staged):
            try:
                with state.LOCK:
                    state.log(name)
                staged.set()
                state.save()
            except BaseException as error:
                errors.append(error)
        server = ThreadingHTTPServer(('127.0.0.1', 0), gateway.Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        connection = http.client.HTTPConnection(*server.server_address, timeout=3)
        self.addCleanup(connection.close)
        first = threading.Thread(target=producer, args=('first', first_staged), daemon=True)
        second = threading.Thread(target=producer, args=('second', second_staged), daemon=True)
        reader = None
        with patch.object(journal, '_append', side_effect=append):
            try:
                first.start()
                self.assertTrue(first_staged.wait(2), 'staging performed file I/O under LOCK')
                self.assertTrue(entered.wait(2))
                second.start()
                self.assertTrue(second_staged.wait(2), 'a blocked flush retained the producer lock')
                connection.request('GET', '/api/ledger')
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual([e['event'] for e in json.loads(response.read())['history']],
                                 ['first', 'second'])
                self.assertTrue(first.is_alive(), 'FIFO should still block publication')
            finally:
                reader = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                for thread in (first, second):
                    if thread.ident is not None:
                        thread.join(5)
                self.assertFalse(first.is_alive())
                self.assertFalse(second.is_alive())
                journal.flush()
                data = os.read(reader, 65536)
                os.close(reader)
        self.assertEqual(errors, [])
        self.assertEqual([json.loads(line)['event'] for line in data.splitlines()], ['first', 'second'])
        self.assertEqual([e['event'] for e in json.loads((self.root / 'cointos.json').read_text())['history']],
                         ['first', 'second'])

    def test_failure_is_published_and_staging_does_not_clear_it(self):
        with state.LOCK:
            state.log('failed record')
        with patch.object(journal, '_append', side_effect=OSError('journal unavailable')):
            state.save()
        self.assertEqual(state.L['journal_error'], 'journal unavailable')
        self.assertEqual(json.loads((self.root / 'cointos.json').read_text())['journal_error'],
                         'journal unavailable')
        with state.LOCK:
            state.log('later record')
        self.assertEqual(state.L['journal_error'], 'journal unavailable')
        state.save()
        self.assertNotIn('journal_error', state.L)
        self.assertNotIn('journal_error', json.loads((self.root / 'cointos.json').read_text()))

    def test_delayed_completion_cannot_hide_a_newer_error(self):
        with patch.object(state, 'JOURNAL_APPLIED', 0), \
             patch.object(journal, 'flush', side_effect=[(2, 'newer failure'), (1, None)]):
            state.flush_journal()
            state.flush_journal()
        self.assertEqual(state.L['journal_error'], 'newer failure')

    def test_shutdown_flushes_diagnostics_even_when_final_ledger_save_fails(self):
        stopping = state.STOPPING.is_set()
        self.addCleanup(state.STOPPING.set if stopping else state.STOPPING.clear)
        with patch.object(daemon, 'system_stopping', return_value=False), \
             patch.object(daemon.lanes, 'save_all'), \
             patch.object(daemon, 'save', side_effect=OSError('ledger unavailable')), \
             contextlib.redirect_stderr(io.StringIO()):
            daemon.shutdown()
        records = [json.loads(line) for line in (self.root / 'events.jsonl').read_text().splitlines()]
        self.assertEqual([r['event'] for r in records], ['daemon stopped', 'shutdown step failed'])
        self.assertEqual(records[-1]['step'], 'save final ledger')
