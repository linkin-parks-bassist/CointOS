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
            with self.subTest(bad=bad), patch.object(halogen, '_call', return_value={**valid, **bad}):
                with self.assertRaises(RuntimeError):
                    halogen.think({'scheduler': {'read_chunk_tokens': 1024}}, 'm', 0, [1, 2], 2, 1, {}, seen.append)
            self.assertEqual(seen, [])

    def test_completed_step_preserves_the_authoritative_vector_and_sampling(self):
        event = {'tokens': [3, 4], 'held': 4, 'done': False, 'generation_seconds': .1}
        seen = []
        with patch.object(halogen, '_call', return_value=event):
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
