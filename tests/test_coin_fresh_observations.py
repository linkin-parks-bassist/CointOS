import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cointos import coin
from tests.test_coin import assistant, call


class FreshObservations(unittest.TestCase):
    def test_read_after_write_observes_current_file_and_cites_current_call(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = root / 'record.txt'
            record.write_text('before\n')
            first = call('fs_read', {'path': str(record)})
            first['id'] = 'before-read'
            second = call('fs_read', {'path': str(record)})
            second['id'] = 'after-read'
            replies = iter([
                assistant(first),
                assistant(call('fs_write', {'path': str(record), 'content': 'after\n', 'overwrite': True})),
                assistant(second),
                assistant(call('done')),
            ])
            captured = []
            def complete(_model, messages, **kwargs):
                captured.append(copy.deepcopy(messages))
                return next(replies)
            with patch.object(coin, 'COIN_STATE', root), patch.object(coin, 'report'), \
                    patch.object(coin, 'complete', side_effect=complete), patch.object(coin, 'send'):
                coin.turn('fixture', 7, 70, [], lambda: [], None,
                          wake={'message': 'Inspect this record.'})
            results = [json.loads(m['content']) for m in captured[-1]
                       if m['role'] == 'tool' and m.get('name') == 'fs_read']
            self.assertEqual([r['content'] for r in results], ['before\n', 'after\n'])
            self.assertEqual([r['evidence_call_id'] for r in results], ['before-read', 'after-read'])
            self.assertNotIn('note', results[-1])

    def test_repeated_effect_is_still_executed_once(self):
        with tempfile.TemporaryDirectory() as directory:
            replies = iter([assistant(call('run_command', {'command': 'effect'})),
                            assistant(call('run_command', {'command': 'effect'})),
                            assistant(call('done'))])
            with patch.object(coin, 'COIN_STATE', Path(directory)), patch.object(coin, 'report'), \
                    patch.object(coin, 'complete', side_effect=lambda *a, **kw: next(replies)), \
                    patch.object(coin, 'invoke', return_value={'ok': True, 'stdout': 'effect'}) as invoke:
                coin.turn('fixture', 7, 70, [], lambda: [], None,
                          wake={'message': 'Inspect this record.'})
            self.assertEqual(invoke.call_count, 1)
