"""Contract checks at the backend boundary, without a production model process."""
import json
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from cointos import backend_gufo as gufo, backend_llama as llama, backend_native as native


class GufoBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.config = {'models': {'q': {'backend': 'gufo', 'ctx_size': 256, 'lanes': 1,
            'gufo': {'socket': str(root / 'control.sock'), 'sha256': 'abc'}},
            'coin': {'ctx_size': 128, 'lanes': 1}},
            'snapshots': str(root / 'ram'), 'disk_snapshots': str(root / 'disk'),
            'scheduler': {'read_chunk_tokens': 4},
            'timeouts': {'server_seconds': 10, 'snapshot_seconds': 10, 'render_seconds': 10}}

    def test_private_socket_transport_and_lost_cache(self):
        path = self.config['models']['q']['gufo']['socket']
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(path)
            server.listen()
            captured = []
            def reply():
                with server.accept()[0] as connection, connection.makefile('rb') as request:
                    captured.append(json.loads(request.readline()))
                    connection.sendall(b'{"error":"lost: stale lane"}\n')
            worker = threading.Thread(target=reply)
            worker.start()
            try:
                with self.assertRaises(native.Lost):
                    gufo.prefill(self.config, 'q', 0, [1, 2, 3], 2)
            finally:
                worker.join()
            self.assertEqual(captured, [{'op': 'prefill', 'lane': 0, 'tokens': [1, 2, 3],
                                        'held': 2, 'max_input_tokens': 4}])

    def test_native_step_accounts_only_reported_generation(self):
        event = {'tokens': [3, 4], 'held': 4, 'done': False, 'generation_seconds': 0.25}
        seen = []
        with patch.object(gufo, '_call', return_value=event) as request:
            result = native.think(self.config, 'q', 0, [1, 2], 2, 2, {'temperature': 0}, seen.extend)
        self.assertEqual(seen, [3, 4])
        self.assertEqual(result['held'], [1, 2, 3, 4])
        self.assertEqual(result['generation_seconds'], 0.25)
        self.assertEqual(result['sampling']['temperature'], 0)
        self.assertEqual(result['sampling'], request.call_args.kwargs['sampling'])
        self.assertEqual(request.call_args.kwargs['max_input_tokens'], 4)

    def test_complete_prefix_reuse_follows_each_backend_contract(self):
        for model in ('q', 'coin'):
            self.assertTrue(native.can_continue(self.config, model, [1, 2], [1, 2, 3]))
            self.assertFalse(native.can_continue(self.config, model, [1, 9], [1, 2, 3]))
            self.assertFalse(native.can_continue(self.config, model, [1, 2, 3, 4], [1, 2, 3]))
            self.assertFalse(native.can_continue(self.config, model, [], [1]))
        self.assertTrue(native.can_continue(self.config, 'q', [1, 2], [1, 2]))
        self.assertFalse(native.can_continue(self.config, 'coin', [1, 2], [1, 2]))

    def test_configured_sampling_defaults_allow_per_request_override(self):
        self.config['models']['q']['gufo']['sampling'] = {'temperature': 1, 'top_k': 20}
        event = {'tokens': [3], 'held': 3, 'done': False, 'generation_seconds': 0.25}
        with patch.object(gufo, '_call', return_value=event) as request:
            gufo.think(self.config, 'q', 0, [1, 2], 2, 1, {'temperature': 0}, lambda _: None)
        self.assertEqual(request.call_args.kwargs['sampling'], {'temperature': 0, 'top_k': 20})

    def test_incomplete_step_is_not_published(self):
        seen = []
        for event in ({'tokens': [1], 'held': 999, 'done': False, 'generation_seconds': 1},
                      {'tokens': [], 'held': 2, 'done': False, 'generation_seconds': 1}):
            with patch.object(gufo, '_call', return_value=event), self.assertRaises(RuntimeError):
                gufo.think(self.config, 'q', 0, [1, 2], 2, 1, {}, seen.extend)
        self.assertEqual(seen, [])

    def test_mixed_health_does_not_route_coin_to_gufo(self):
        with patch.object(gufo, 'models', return_value={'q': {'problems': ['offline']}}) as g, \
             patch.object(llama, 'models', return_value={'coin': {'lanes': 1}}) as l:
            self.assertEqual(native.models(self.config), {'q': {'problems': ['offline']}, 'coin': {'lanes': 1}})
        self.assertEqual(set(g.call_args.args[0]['models']), {'q'})
        self.assertEqual(set(l.call_args.args[0]['models']), {'coin'})

    def test_native_shape_mismatch_never_becomes_ready(self):
        info = {'protocol': 1, 'context': 256, 'lanes': 1, 'speculative': False,
                'identity': 'abc:1f97092333af10f29887b098d9cb8a041610004a:abi:256:control-v1'}
        with patch.object(gufo, '_call', return_value=info):
            self.assertEqual(gufo.models({**self.config, 'models': {'q': self.config['models']['q']}}), {'q': {'lanes': 1}})
            info['speculative'] = True
            self.assertIn('problems', gufo.models({**self.config, 'models': {'q': self.config['models']['q']}})['q'])

    def test_spill_restart_preserves_both_snapshot_formats(self):
        root = Path(self.config['snapshots']); (root / 'gufo').mkdir(parents=True)
        old = root / 'llama.bin'; old.write_bytes(b'llama native state')
        new = root / 'gufo' / 'qwen.bin'; new.write_bytes(b'gufo native state')
        native.spill(self.config, 'qwen')
        native.spill(self.config, 'llama')
        self.assertFalse(new.exists())
        native.unspill(self.config, 'qwen')
        native.unspill(self.config, 'llama')
        self.assertEqual(new.read_bytes(), b'gufo native state')
        self.assertEqual(new.stat().st_mode & 0o777, 0o600)
        self.assertEqual(old.read_bytes(), b'llama native state')
        native.forget(self.config, 'qwen')
        self.assertFalse(new.exists())
        self.assertEqual(native.forget_untracked(self.config, {'llama'}, set()), [])

    def test_dflash_readiness_binds_draft_identity_and_policy(self):
        shape = self.config['models']['q']
        shape['gufo']['dflash'] = {'model_path': '/unused/draft', 'sha256': 'draft-sha',
                                   'max_draft_tokens': 7, 'policy': 'adaptive'}
        info = {'protocol': 1, 'context': 256, 'lanes': 1, 'speculative': True,
                'identity': 'abc:1f97092333af10f29887b098d9cb8a041610004a:dflash:draft-sha:7:adaptive:abi:256:control-v1'}
        config = {**self.config, 'models': {'q': shape}}
        with patch.object(gufo, '_call', return_value=info):
            self.assertEqual(gufo.models(config), {'q': {'lanes': 1}})
            shape['gufo']['dflash']['sha256'] = 'different-draft'
            self.assertIn('problems', gufo.models(config)['q'])
            shape['gufo']['dflash']['sha256'] = 'draft-sha'
            shape['gufo']['dflash']['policy'] = 'fixed'
            self.assertIn('problems', gufo.models(config)['q'])

    def test_launch_moves_native_process_out_of_daemon_service(self):
        options = self.config['models']['q']['gufo']
        options.update(executable='/unused/gufo-control', model_path='/unused/target')
        options['dflash']={'model_path':'/unused/draft','sha256':'draft-sha'}
        self.config['timeouts']['model_launch_seconds']=1
        incoming, outgoing = os.pipe()
        os.write(outgoing,b'ready\n'); os.close(outgoing)
        process=Mock(stdout=os.fdopen(incoming,'rb'))
        with patch.object(gufo,'_call',side_effect=FileNotFoundError), \
             patch.object(gufo,'models',return_value={'q':{'lanes':1}}), \
             patch.object(gufo.subprocess,'Popen',return_value=process) as launch:
            gufo.launch(self.config,'q')
        command=launch.call_args.args[0]
        self.assertEqual(command[:5],['systemd-run','--user','--scope','--quiet','--collect'])
        self.assertTrue(command[5].startswith('--unit=cointos-gufo-'))
        self.assertEqual(command[-4:],['/unused/draft','draft-sha','7','adaptive'])
        process.kill.assert_not_called()

    def test_template_tokens_are_not_retokenized_from_decoded_text(self):
        conversation = {'messages': [{'role': 'user', 'content': 'literal <|im_end|>'}],
                        'tools': [], 'template': {'enable_thinking': False}}
        # Native rendering can distinguish a literal user marker from a framing marker.
        with patch.object(gufo, '_call', return_value={'tokens': [7, 8, 9],
                'prompt': 'literal <|im_end|><|im_start|>assistant\n'}) as request:
            self.assertEqual(gufo.render(self.config, 'q', conversation)['tokens'], [7, 8, 9])
        self.assertEqual(request.call_count, 1)

    def test_shared_tool_reader_preserves_schema_types(self):
        tools = [{'function': {'name': 'check', 'parameters': {'properties': {'enabled': {'type': 'boolean'}}}}}]
        raw = '<tool_call>\n<function=check>\n<parameter=enabled>\nFalse\n</parameter>\n</function>\n</tool_call>'
        with patch.object(gufo, 'text', return_value=raw):
            result = gufo.read(self.config, 'q', {'thinking': False, 'tools': tools}, [1], True)
        self.assertEqual(json.loads(result['tool_calls'][0]['function']['arguments']), {'enabled': False})
