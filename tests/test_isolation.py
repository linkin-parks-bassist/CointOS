"""Test imports must redirect every captured runtime path before loading production code."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class Isolation(unittest.TestCase):
    def run_child(self, code, directory):
        return subprocess.run([sys.executable, '-c', code],
                              env={**os.environ, 'COINTOS_STATE': str(directory),
                                   'KT_CONFIG': str(Path(directory) / 'roots.json')},
                              capture_output=True, text=True)

    def test_late_isolation_refuses_before_fixture_events_or_state_can_escape(self):
        with tempfile.TemporaryDirectory() as root:
            sentinel = Path(root) / 'events.jsonl'
            sentinel.write_text('preserved live evidence\n')
            result = self.run_child('''
from cointos import state
try:
    import tests
except RuntimeError as error:
    assert 'Import tests before cointos' in str(error)
    print('rejected unsafe import order')
else:
    state.L.update(state.fresh({}))
    state.log('fixture pollution')
''', root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('rejected unsafe import order', result.stdout)
            self.assertEqual(sentinel.read_text(), 'preserved live evidence\n')

    def test_real_queue_publication_and_registration_stay_in_disposable_roots(self):
        with tempfile.TemporaryDirectory() as root:
            policy = Path(root) / 'roots.json'
            policy.write_text('{"preserved": "live registration"}\n')
            result = self.run_child('''
import os
from pathlib import Path
import subprocess
from unittest.mock import patch
import tests
from cointos import config, kt, queues, state
write = kt.write
def isolated_write(root, question, body):
    # Refuse before a regression can write into the real source/installed tree.
    assert Path(root).is_relative_to(config.STATE), root
    assert Path(os.environ['KT_CONFIG']).is_relative_to(config.STATE)
    assert Path(os.environ['KT_GLOBAL_ROOT']).is_relative_to(config.STATE)
    assert Path(os.environ['KT_REWRITE_STATE_DIR']).is_relative_to(config.STATE)
    return write(root, question, body)
state.L.update(state.fresh({}))
queues.add({'name': 'fixture'}, 'queued', 'isolated', 'Real generated queue evidence')
with patch.object(kt, 'write', side_effect=isolated_write):
    queues.publish()
opened = subprocess.run(['kt', '--lean', 'open', 'local:what/is/queued.md'],
                        cwd=queues.ROOT, check=True, capture_output=True, text=True)
assert 'fixture:isolated' in opened.stdout
assert 'Real generated queue evidence' in opened.stdout
''', root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(Path(root).iterdir()), [policy])
            self.assertEqual(policy.read_text(), '{"preserved": "live registration"}\n')

    def test_test_first_import_isolates_real_journal_and_ledger_writes(self):
        with tempfile.TemporaryDirectory() as root:
            sentinel = Path(root) / 'events.jsonl'
            sentinel.write_text('preserved live evidence\n')
            result = self.run_child('''
import os
from pathlib import Path
original = Path(os.environ['COINTOS_STATE'])
import tests
from cointos import config, journal, keys, opencode, state
assert config.STATE != original
assert journal.STATE == opencode.STATE == config.STATE
assert keys.KEYS.parent == config.STATE
assert Path(state.CONFIG['snapshots']).is_relative_to(config.STATE)
assert Path(state.CONFIG['disk_snapshots']).is_relative_to(config.STATE)
state.L.update(state.fresh({}))
state.log('isolated fixture')
state.save()
assert (config.STATE/'cointos.json').is_file()
assert 'isolated fixture' in (config.STATE/'events.jsonl').read_text()
''', root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(Path(root).iterdir()), [sentinel])
            self.assertEqual(sentinel.read_text(), 'preserved live evidence\n')
