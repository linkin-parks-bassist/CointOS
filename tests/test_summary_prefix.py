"""Summary cache reuse cannot authorize tools or exceed the actual token window."""
import copy
import json
import unittest
from unittest.mock import patch
from cointos import gateway, state, backend_llama


class SummaryPrefix(unittest.TestCase):
    def setUp(self):
        previous = copy.deepcopy(state.L)
        self.addCleanup(lambda: (state.L.clear(), state.L.update(previous)))
        state.L.clear()
        state.L.update(state.fresh({}))
        state.L['agents']['a'] = {'task': 't'}
        state.L['tasks']['t'] = {'id': 't', 'session': 's'}
        self.model = state.CONFIG['work_model']
        self.tools = [{'type': 'function', 'function': {'name': 'bash', 'parameters': {}}}]
        gateway.stable_environment([{'role': 'system', 'content': 'ordinary system'}], 'a')
        gateway.stable_tools(self.tools, 'a')
        self.body = {'max_tokens': 64, 'messages': [
            {'role': 'system', 'content': 'compaction system'},
            {'role': 'user', 'content': 'original assignment'},
            {'role': 'assistant', 'content': 'completed work'},
            {'role': 'user', 'content': json.dumps({'c': 'summary instructions', 'f': 'flattened fallback'})}]}

    def render(self):
        return gateway.render_request(self.body, 'a', self.model, {}, summary=True)

    def test_pinned_declarations_render_but_do_not_authorize_tools(self):
        with patch.object(gateway.BACKEND, 'render', return_value={'tokens': [1, 2], 'reader': {}}) as render:
            result = self.render()
        conversation = render.call_args.args[2]
        self.assertEqual(conversation['tools'], self.tools)
        self.assertEqual(conversation['messages'][0]['content'], 'ordinary system')
        self.assertEqual(conversation['messages'][1]['content'], 'original assignment')
        self.assertIn('summary instructions', conversation['messages'][-1]['content'])
        self.assertNotIn('flattened fallback', str(conversation['messages']))
        self.assertFalse(result['reader']['allow_tools'])

    def test_exact_window_overflow_uses_flattened_fallback_without_declarations(self):
        shape = state.CONFIG['models'][self.model]
        window = shape['ctx_size'] // shape['lanes']
        with patch.object(gateway.BACKEND, 'render', side_effect=[
                {'tokens': [0] * window, 'reader': {}}, {'tokens': [1, 2], 'reader': {}}]) as render:
            result = self.render()
        fallback = render.call_args.args[2]
        self.assertIsNone(fallback['tools'])
        self.assertEqual(fallback['messages'], [{'role': 'system', 'content': 'ordinary system'},
                                              {'role': 'user', 'content': 'flattened fallback'}])
        self.assertEqual(result['tokens'], [1, 2])
        self.assertFalse(result['reader']['allow_tools'])

    def test_no_pinned_tools_uses_fallback(self):
        state.L['tasks']['t'].pop('tool_context')
        with patch.object(gateway.BACKEND, 'render', return_value={'tokens': [1], 'reader': {}}) as render:
            result = self.render()
        self.assertEqual(render.call_args.args[2]['messages'][-1]['content'], 'flattened fallback')
        self.assertIsNone(render.call_args.args[2]['tools'])
        self.assertEqual(render.call_count, 1)
        self.assertFalse(result['reader']['allow_tools'])

    def test_exact_fit_retains_the_structured_prefix(self):
        shape = state.CONFIG['models'][self.model]
        window = shape['ctx_size'] // shape['lanes']
        with patch.object(gateway.BACKEND, 'render', return_value={
                'tokens': [0] * (window - 64), 'reader': {}}) as render:
            self.render()
        self.assertEqual(render.call_count, 1)
        self.assertEqual(render.call_args.args[2]['tools'], self.tools)

    def test_nontext_envelope_is_rejected(self):
        self.body['messages'][-1]['content'] = [{'type': 'text', 'text': '{}'}]
        with self.assertRaises(ValueError):
            self.render()

    def test_unmanaged_requests_and_bad_envelopes_cannot_enter_the_protocol(self):
        with self.assertRaises(ValueError):
            gateway.render_request(self.body, 'user', self.model, {}, summary=True)
        self.body['tools'] = self.tools
        with self.assertRaises(ValueError): self.render()
        del self.body['tools']
        self.body['messages'][-1]['content'] = '{}'
        with self.assertRaises(ValueError): self.render()

    def test_tool_markup_stays_text_in_tool_free_replies(self):
        text = 'Example:\n<tool_call>\n<function=bash>\n<parameter=command>\nprintf x\n</parameter>\n</function>\n</tool_call>'
        reader = {'thinking': False, 'tools': self.tools, 'allow_tools': False}
        with patch.object(backend_llama, '_server', return_value={'content': text}):
            for final in (False, True):
                result = backend_llama.read(state.CONFIG, self.model, reader, [1], final)
                self.assertEqual(result['tool_calls'], [])
                if final: self.assertEqual(result['content'], text)


if __name__ == '__main__': unittest.main()
