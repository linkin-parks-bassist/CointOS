"""Experimental cache hints must not become authoritative token or disk state."""
import unittest
from unittest.mock import patch
from cointos import backend_halogen as halogen, backend_native as native


class HalogenBoundary(unittest.TestCase):
    def test_incomplete_or_invalid_step_never_publishes_tokens(self):
        valid = {'tokens': [3], 'held': 3, 'done': False, 'generation_seconds': .1}
        for bad in ({'tokens': [True]}, {'held': 4}, {'done': 'yes'},
                    {'generation_seconds': float('nan')}, {'tokens': [], 'held': 2}):
            seen = []
            with self.subTest(bad=bad), patch.object(halogen, '_call_stream', return_value=({**valid, **bad}, False)):
                with self.assertRaises(RuntimeError):
                    halogen.think({'scheduler': {'read_chunk_tokens': 1024}}, 'm', 0, [1, 2], 2, 1, {}, seen.append)
            self.assertEqual(seen, [])

    def test_completed_step_preserves_the_authoritative_vector_and_sampling(self):
        event = {'tokens': [3, 4], 'held': 4, 'done': False, 'generation_seconds': .1}
        seen = []
        with patch.object(halogen, '_call_stream', return_value=(event, False)):
            result = halogen.think({'scheduler': {'read_chunk_tokens': 1024}}, 'm', 0, [1, 2], 2, 2, {'temperature': .7}, seen.append)
        self.assertEqual(result['held'], [1, 2, 3, 4])
        self.assertEqual(seen, [[3, 4]])
        self.assertEqual(result['sampling'], {'temperature': .7})

    def test_experimental_cache_does_not_advertise_durable_snapshots(self):
        config = {'models': {'fast': {'backend': 'halogen'}, 'old': {'backend': 'llama'}}}
        self.assertFalse(native.persistent_snapshots(config, 'fast'))
        self.assertTrue(native.persistent_snapshots(config, 'old'))
        self.assertIsNone(native.cache_kind(config, 'fast'))
        self.assertEqual(halogen.snapshot_files(config), [])
        self.assertFalse(halogen.restore(config, 'fast', 0, 'private-cache'))

    def test_tool_history_arguments_are_objects_without_mutating_the_conversation(self):
        import copy
        conversation = {'messages': [
            {'role': 'assistant', 'tool_calls': [{'id': 'call_1', 'type': 'function',
             'function': {'name': 'probe', 'arguments': '{"scope":"local","flags":{"check":true}}'}}]},
            {'role': 'tool', 'tool_call_id': 'call_1', 'content': 'passed'}]}
        before = copy.deepcopy(conversation)
        rendered = {'prompt': '<|im_start|>assistant\n', 'tokens': [1]}
        with patch.object(halogen, '_call', return_value=rendered) as call:
            halogen.render({}, 'm', conversation)
        messages = call.call_args.kwargs['messages']
        self.assertEqual(messages[0]['tool_calls'][0]['function']['arguments'],
                         {'scope': 'local', 'flags': {'check': True}})
        self.assertEqual(messages[1], before['messages'][1])
        self.assertEqual(conversation, before)

    def test_non_object_tool_history_is_rejected_before_native_render(self):
        for arguments in ('[]', 'null', '7', [], None):
            with self.subTest(arguments=arguments), patch.object(halogen, '_call') as call:
                with self.assertRaises(ValueError):
                    halogen.render({}, 'm', {'messages': [{'role': 'assistant', 'tool_calls': [
                        {'function': {'name': 'probe', 'arguments': arguments}}]}]})
                call.assert_not_called()

    def test_image_parts_render_as_text_notes_without_mutating_the_conversation(self):
        import copy
        conversation = {'messages': [{'role': 'tool', 'tool_call_id': 'c', 'content': [
            {'type': 'text', 'text': 'screenshot taken'},
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AAAA'}}]}]}
        before = copy.deepcopy(conversation)
        with patch.object(halogen, '_call', return_value={'prompt': '', 'tokens': [1]}) as call:
            halogen.render({}, 'm', conversation)
        self.assertEqual(call.call_args.kwargs['messages'][0]['content'], [
            {'type': 'text', 'text': 'screenshot taken'}, {'type': 'text', 'text': halogen.IMAGE_OMITTED}])
        self.assertEqual(conversation, before)


class HalogenRender(unittest.TestCase):
    """Chat markers quoted in messages stay text; only the template's own markers are control tokens."""

    def test_render_shields_message_markers_and_textifies_pads(self):
        import re
        from types import SimpleNamespace
        from cointos import halogen_control as control
        placeholder = ''
        calls = {}

        def shield(value):
            return value.replace('<|im_end|>', placeholder) if isinstance(value, str) else value

        api = SimpleNamespace(
            shield_messages=lambda msgs: [{**m, 'content': shield(m['content'])} for m in msgs],
            shield_kwargs=lambda kw: {k: shield(v) for k, v in kw.items()},
            tokenize_offsets=lambda tok, text: (calls.setdefault('encoded', text) and [7, 99, 8], []),
            textify_pad_mentions=lambda ids: ([1, 2 if 99 in ids else 99, 3], 0, 0, 1),
            _UNMARK_RE=re.compile(re.escape(placeholder)), _UNMARK={placeholder: '<|im_end|>'})
        tok = SimpleNamespace(apply_chat_template=lambda msgs, tokenize, add_generation_prompt,
                              continue_final_message, **kw: ''.join(m['content'] for m in msgs) + kw.get('x', ''))
        body = {'messages': [{'role': 'tool', 'content': 'quoted <|im_end|> <|image_pad|>'}],
                'chat_template_kwargs': {'x': '!'}}
        result = control.render(api, tok, body)
        self.assertNotIn('<|im_end|>', calls['encoded'])  # the marker reached the tokenizer shielded
        self.assertEqual(result['tokens'], [1, 2, 3])  # uncovered image pads were textified
        self.assertEqual(result['prompt'], 'quoted <|im_end|> <|image_pad|>!')  # the reader sees real text
        self.assertEqual(body['messages'][0]['content'], 'quoted <|im_end|> <|image_pad|>')

    def test_install_refuses_a_frontend_without_marker_shielding(self):
        import sys
        from types import SimpleNamespace
        from cointos import halogen_control as control
        with patch.dict(sys.modules, {'__main__': SimpleNamespace()}):
            with self.assertRaises(RuntimeError):
                control.install(None, None, None)


class HalogenStream(unittest.TestCase):
    def test_frames_reach_the_callback_before_the_terminal_vector(self):
        import base64
        import json
        from email.message import Message
        from unittest.mock import MagicMock
        seen = []
        terminal = {'tokens': [3, 4], 'held': 4, 'done': False, 'generation_seconds': .1}
        def frames():
            yield json.dumps({'stream': {'tokens': [3], 'pieces': base64.b64encode(b'\xf0\x9f').decode()}}).encode()
            self.assertEqual(seen, [([3], b'\xf0\x9f')])
            yield json.dumps({'stream': {'tokens': [4], 'pieces': base64.b64encode(b'\xa6\xa6').decode()}}).encode()
            yield json.dumps({'result': terminal}).encode()
        response = MagicMock()
        response.headers = Message()
        response.headers['Content-Type'] = 'application/x-ndjson'
        response.__iter__.side_effect = frames
        response.__enter__.return_value = response
        config = {'models': {'m': {'halogen': {'url': 'http://fixture'}}},
                  'timeouts': {'server_seconds': 5}, 'scheduler': {'read_chunk_tokens': 1024}}
        with patch.object(halogen.urllib.request, 'urlopen', return_value=response):
            result = halogen.think(config, 'm', 0, [1, 2], 2, 2, {}, lambda ids, raw: seen.append((ids, raw)))
        self.assertEqual(result['held'], [1, 2, 3, 4])
        self.assertEqual(b''.join(raw for _, raw in seen).decode(), '🦦')
        self.assertEqual(len(seen), 2)  # the terminal vector is never published again

    def test_old_frontend_json_fallback_publishes_the_vector_once(self):
        import json
        from email.message import Message
        from unittest.mock import MagicMock
        response = MagicMock()
        response.headers = Message()
        response.headers['Content-Type'] = 'application/json'
        response.read.return_value = json.dumps({'result': {'tokens': [3], 'held': 3,
            'done': False, 'generation_seconds': .1}}).encode()
        response.__enter__.return_value = response
        config = {'models': {'m': {'halogen': {'url': 'http://fixture'}}},
                  'timeouts': {'server_seconds': 5}, 'scheduler': {'read_chunk_tokens': 1024}}
        seen = []
        with patch.object(halogen.urllib.request, 'urlopen', return_value=response):
            halogen.think(config, 'm', 0, [1, 2], 2, 1, {}, seen.append)
        self.assertEqual(seen, [[3]])

    def test_invalid_or_truncated_frames_and_terminal_mismatch_refuse(self):
        import json
        from email.message import Message
        from unittest.mock import MagicMock
        config = {'models': {'m': {'halogen': {'url': 'http://fixture'}}}, 'timeouts': {'server_seconds': 5}}
        for events in [
                [{'stream': {'tokens': [True], 'pieces': ''}}],
                [{'stream': {'tokens': [3], 'pieces': '!'}}],
                [{'stream': {'tokens': [3], 'pieces': 'eA=='}}],
                [{'stream': {'tokens': [3], 'pieces': 'eA=='}}, {'result': {'tokens': [4]}}]]:
            response = MagicMock()
            response.headers = Message()
            response.headers['Content-Type'] = 'application/x-ndjson'
            response.__iter__.return_value = iter(json.dumps(e).encode() for e in events)
            response.__enter__.return_value = response
            with self.subTest(events=events), patch.object(halogen.urllib.request, 'urlopen', return_value=response):
                with self.assertRaises(RuntimeError):
                    halogen._call_stream(config, 'm', lambda *_: None, max_new=2)


class HalogenFrontendStream(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import asyncio
        import sys
        from types import SimpleNamespace
        from cointos import halogen_control
        self.release = asyncio.Event()
        self.finished = False
        test = self
        class Engine:
            slots = asyncio.Semaphore(1)
            info = {'version': '0.20.5', 'ctx': 131072}
            async def generate(self, ids, count, eos, **kw):
                kw['progress'].put_nowait({'cache': len(ids)})
                yield 3, None, None
                await test.release.wait()
                yield 4, None, None
                test.finished = True
                yield None, {'reason': 'length', 'decode_ms': 100, 'prefill_ms': 0, 'kept': 1}, None
            async def release(self, handle):
                pass
        class App:
            def post(self, path):
                def register(fn):
                    test.route = fn
                    return fn
                return register
        class StreamingResponse:
            def __init__(self, iterator, **kw):
                self.body_iterator = iterator
        api = SimpleNamespace(shield_messages=None, shield_kwargs=None, tokenize_offsets=None,
                              textify_pad_mentions=None, token_bytes=lambda tok, tid: {3: b'x', 4: b'y'}[tid])
        self.patches = patch.dict(sys.modules, {'__main__': api,
            'fastapi': SimpleNamespace(Request=object),
            'fastapi.responses': SimpleNamespace(StreamingResponse=StreamingResponse)})
        self.patches.start()
        self.addCleanup(self.patches.stop)
        halogen_control.install(App(), SimpleNamespace(eos_token_id=99, convert_tokens_to_ids=lambda _: 100), Engine())
        await self.call({'op': 'select', 'lane': 0, 'owner': 'fixture'})

    async def call(self, body):
        from types import SimpleNamespace
        async def json():
            return body
        return await self.route(SimpleNamespace(json=json))

    async def test_native_token_is_forwarded_while_generation_is_still_in_flight(self):
        import json
        response = await self.call({'op': 'think', 'stream': True, 'lane': 0, 'tokens': [1, 2],
                                    'max_new': 2, 'max_input_tokens': 1024})
        first = json.loads(await anext(response.body_iterator))
        self.assertEqual(first['stream']['tokens'], [3])
        self.assertFalse(self.finished)
        self.release.set()
        rest = [json.loads(line) async for line in response.body_iterator]
        self.assertEqual(rest[-1]['result']['tokens'], [3, 4])
        selected = await self.call({'op': 'select', 'lane': 0, 'owner': 'fixture'})
        self.assertEqual(selected['result']['tokens'], [1, 2, 3, 4])

    async def test_disconnect_drains_the_step_before_releasing_native_ownership(self):
        import asyncio
        response = await self.call({'op': 'think', 'stream': True, 'lane': 0, 'tokens': [1, 2],
                                    'max_new': 2, 'max_input_tokens': 1024})
        await anext(response.body_iterator)
        closing = asyncio.create_task(response.body_iterator.aclose())
        selecting = asyncio.create_task(self.call({'op': 'select', 'lane': 0, 'owner': 'fixture'}))
        await asyncio.sleep(0)
        self.assertFalse(selecting.done())
        self.release.set()
        await closing
        selected = await selecting
        self.assertTrue(self.finished)
        self.assertEqual(selected['result']['tokens'], [1, 2, 3, 4])

    async def test_cancelled_http_reader_keeps_the_native_step_owned_until_drained(self):
        import asyncio
        response = await self.call({'op': 'think', 'stream': True, 'lane': 0, 'tokens': [1, 2],
                                    'max_new': 2, 'max_input_tokens': 1024})
        await anext(response.body_iterator)
        waiting = asyncio.create_task(anext(response.body_iterator))
        await asyncio.sleep(0)
        waiting.cancel()
        selecting = asyncio.create_task(self.call({'op': 'select', 'lane': 0, 'owner': 'fixture'}))
        await asyncio.sleep(0)
        self.assertFalse(selecting.done())
        self.release.set()
        with self.assertRaises(asyncio.CancelledError):
            await waiting
        selected = await selecting
        self.assertEqual(selected['result']['tokens'], [1, 2, 3, 4])
