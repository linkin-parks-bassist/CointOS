"""Real catalog parsing and replacement transactions; native launch is the I/O boundary."""
import copy
import json
from pathlib import Path
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from cointos import backend_llama, daemon, models, state
from tests import support


def gguf(path, architecture='qwen35'):
    def string(s):
        b = s.encode(); return struct.pack('<Q', len(b)) + b
    fields = [('general.architecture', architecture), ('general.name', 'fixture')]
    path.write_bytes(b'GGUF' + struct.pack('<IQQ', 3, 1, len(fields)) + b''.join(
        string(k) + struct.pack('<I', 8) + string(v) for k, v in fields))


class ModelSelection(unittest.TestCase):
    def setUp(self):
        saved = copy.deepcopy(state.CONFIG)
        self.addCleanup(lambda: (state.CONFIG.clear(), state.CONFIG.update(saved)))
        state.CONFIG['work_model'] = next(name for name, shape in state.CONFIG['models'].items()
                                          if shape.get('backend') == 'gufo')
        support.fresh_ledger(self)
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = self.root / 'config.json'
        self.enterContext(patch.object(models.configuration, 'CONFIG', self.path))
        self.enterContext(patch.object(models, 'save'))
        self.enterContext(patch.object(models.lanes, 'worker'))
        self.enterContext(patch.object(models.memory, 'measure', return_value={'available_gb': 100}))
        self.enterContext(patch.object(models.BACKEND, 'budget', return_value=None))
        self.enterContext(patch.object(models.snapshots, 'make_room', return_value=True))
        self.kill = self.enterContext(patch.object(models.BACKEND, 'kill'))
        self.launch = self.enterContext(patch.object(models.BACKEND, 'launch'))
        self.old = state.CONFIG['work_model']
        state.CONFIG['coin'].pop('model', None)
        default_file = self.root / 'original.gguf'; gguf(default_file)
        state.CONFIG['models'][self.old]['gufo']['model_path'] = str(default_file)
        self.target = self.root / 'target.gguf'; gguf(self.target)
        state.CONFIG['model_directories'] = [str(self.root)]
        state.L['models'][self.old]['up'] = True
        state.L['model_change'] = {'phase': 'checking'}
        self.path.write_text(json.dumps(state.CONFIG))

    def test_catalog_reads_metadata_excludes_companions_and_marks_unsupported(self):
        gguf(self.root / 'draft-DFlash2.gguf')
        gguf(self.root / 'other.gguf', 'unqualified')
        (self.root / 'broken.gguf').write_bytes(b'GGUF')
        (self.root / 'partial.gguf.partial').write_bytes(b'GGUF')
        choices = {e['name']: e for e in models.catalog()}
        self.assertTrue(choices['target']['available'])
        self.assertFalse(choices['other']['available'])
        self.assertFalse(choices['broken']['available'])
        self.assertNotIn('draft-DFlash2', choices)
        self.assertNotIn('partial.gguf', choices)

    def test_discovery_parses_each_unchanged_file_once_and_rereads_a_changed_one(self):
        self.enterContext(patch.dict(models.PARSED, clear=True))
        broken = self.root / 'broken.gguf'; broken.write_bytes(b'GGUF')
        real = models.parse
        with patch.object(models, 'parse', side_effect=real) as parse:
            first = models.catalog()
            parsed = parse.call_count
            self.assertEqual(models.catalog(), first)  # neither good nor broken files are reparsed
            self.assertEqual(parse.call_count, parsed)
            gguf(broken, 'unqualified')  # completed in place: new size and mtime
            choices = {e['name']: e for e in models.catalog()}
            self.assertEqual(parse.call_count, parsed + 1)
        self.assertEqual(choices['broken']['architecture'], 'unqualified')

    def test_replacement_drains_replies_preserves_agents_and_persists_only_model_fields(self):
        state.L['agents']['survivor'] = {'session': 'retained'}
        state.ACTIVE['chats'] = 1
        self.addCleanup(lambda: state.ACTIVE.update(chats=0))
        thread = threading.Thread(target=models.replace, args=(str(self.target),))
        thread.start()
        deadline = time.monotonic() + 2
        while state.L['model_change']['phase'] != 'draining' and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(state.L['model_change']['phase'], 'draining')
        self.kill.assert_not_called()
        self.kill.side_effect = lambda *args: self.assertEqual(
            json.loads(self.path.read_text())['work_model'], 'target')
        with state.LOCK:
            state.ACTIVE['chats'] = 0
            state.LOCK.notify_all()
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(state.CONFIG['work_model'], 'target')
        self.assertEqual(models.resolve(self.old), 'target')  # surviving clients follow the default
        self.assertEqual(models.resolve('default'), 'target')
        self.assertEqual(state.L['agents']['survivor']['session'], 'retained')
        self.assertEqual(state.L['model_change']['phase'], 'ready')
        self.assertEqual(json.loads(self.path.read_text())['work_model'], 'target')
        self.assertFalse(state.L['models'][self.old]['up'])
        self.assertTrue(state.L['models']['target']['up'])
        self.kill.assert_called_once()
        self.assertNotIn('dflash', state.CONFIG['models']['target']['gufo'])

    def test_failed_load_restores_previous_model_and_keeps_persistent_choice(self):
        before = self.path.read_bytes()
        self.launch.side_effect = [RuntimeError('bad weights'), None]
        models.replace(str(self.target))
        self.assertEqual(json.loads(self.path.read_bytes()), json.loads(before))
        self.assertEqual(state.CONFIG['work_model'], self.old)
        self.assertEqual(state.L['model_change']['phase'], 'failed')
        self.assertIn('bad weights', state.L['model_change']['error'])
        self.assertEqual(self.launch.call_args_list[-1].args[1], self.old)

    def test_lemonade_recipe_is_selectable_without_reading_its_protected_weights(self):
        name = 'Flash-Next'
        shape = {'backend': 'llama', 'ctx_size': 8192, 'lanes': 1,
                 'weights_gb': 60, 'memory_gb': 70, 'args': '--spec-type none', 'resident': True}
        state.CONFIG['models'][name] = shape
        state.CONFIG['model_directories'] = ['/does-not-exist/protected-cache']
        with patch.object(backend_llama, '_call', return_value={'data': [
                {'id': 'user.' + name, 'downloaded': True}]}):
            entry = next(e for e in models.catalog() if e['model'] == name)
            self.assertTrue(entry['available'])
            self.assertEqual(entry['id'], 'lemonade:' + name)
            models.replace(entry['id'])
        self.assertEqual(state.CONFIG['work_model'], name)
        self.assertEqual(models.status()['path'], 'lemonade:' + name)
        self.launch.assert_called_once()
        self.assertEqual(self.launch.call_args.args[0]['models'][name], shape)

    def test_unavailable_lemonade_model_does_not_replace_the_default(self):
        state.CONFIG['models']['missing'] = {'backend': 'llama'}
        with patch.object(backend_llama, '_call', return_value={'data': []}):
            models.replace('lemonade:missing')
        self.assertEqual(state.CONFIG['work_model'], self.old)
        self.assertIn('not downloaded', state.L['model_change']['error'])
        self.kill.assert_not_called()

    def test_shared_default_preserves_private_session_support_before_unloading(self):
        state.CONFIG['models']['nonresident'] = {'backend': 'llama', 'resident': False}
        with patch.object(backend_llama, '_call', return_value={'data': [
                {'id': 'nonresident', 'downloaded': True}]}):
            models.replace('lemonade:nonresident')
        self.assertEqual(state.CONFIG['work_model'], self.old)
        self.assertIn('private sessions', state.L['model_change']['error'])
        self.kill.assert_not_called()
        self.launch.assert_not_called()

    def test_failed_persistence_restores_previous_engine(self):
        with patch.object(models.configuration, 'write_json', side_effect=OSError('disk full')):
            models.replace(str(self.target))
        self.assertEqual(state.CONFIG['work_model'], self.old)
        self.assertEqual(state.L['model_change']['phase'], 'failed')
        self.assertIn('disk full', state.L['model_change']['error'])

    def test_only_required_models_are_launched_and_switch_blocks_reconciliation(self):
        state.CONFIG['models']['unused'] = copy.deepcopy(state.CONFIG['models'][self.old])
        state.L['models']['unused'] = {'up': False, 'launching': False, 'problems': []}
        with patch.object(daemon.BACKEND, 'models', return_value={self.old: {}}) as poll:
            daemon.check_models()
            self.assertNotIn('unused', poll.call_args.args[0]['models'])
            state.L['model_change']['phase'] = 'loading'
            daemon.check_models()
            self.assertEqual(poll.call_count, 1)
