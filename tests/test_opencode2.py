"""Protocol migration preserves conversation identity and CointOS authority."""
import copy
import json
import unittest

from cointos import frontier, gateway, opencode2, sessions, state, tasks
from tests import support


class MigrationVerification(unittest.TestCase):
    def setUp(self):
        self.source = {'info': {'id': 'ses_original'}, 'messages': [
            {'info': {'id': 'msg_user', 'role': 'user', 'time': {'created': 123}, 'summary': {'diffs': []}},
             'parts': [{'type': 'text', 'text': 'Keep the original task.'}]},
            {'info': {'id': 'msg_assistant', 'role': 'assistant'}, 'parts': [
                {'type': 'tool', 'callID': 'call_once', 'tool': 'bash',
                 'state': {'status': 'completed', 'input': {'command': 'effect'}, 'output': 'Recorded effect'}}]}]}
        self.target = {'info': {'id': 'ses_original'}, 'messages': [
            {'type': 'user', 'id': 'msg_user', 'time': {'created': 123}, 'text': 'Keep the original task.'},
            {'type': 'assistant', 'id': 'msg_assistant', 'content': [
                {'type': 'tool', 'id': 'call_once', 'name': 'bash', 'state': {
                    'status': 'completed', 'input': {'command': 'effect'},
                    'content': [{'type': 'text', 'text': 'Recorded effect'}]}}]}]}

    def test_native_projection_preserves_user_and_completed_tool_effect(self):
        sessions.verify_v2(self.source, self.target)

    def test_lost_history_changed_identity_and_changed_effect_fail_closed(self):
        variants = []
        for field, value in [('id', 'replacement'), ('text', 'Rewritten task'), ('time', {'created': 124})]:
            target = copy.deepcopy(self.target); target['messages'][0][field] = value; variants.append(target)
        target = copy.deepcopy(self.target); target['messages'].pop(); variants.append(target)
        target = copy.deepcopy(self.target)
        target['messages'][1]['content'][0]['state']['content'][0]['text'] = 'Different effect'; variants.append(target)
        for target in variants:
            with self.subTest(target=target), self.assertRaises(ValueError):
                sessions.verify_v2(self.source, target)

    def test_resume_selection_reuses_only_unfinished_execution(self):
        user = {'type': 'user', 'id': 'original'}
        for finish, error, expected in [(None, {}, True), ('tool-calls', {}, True),
                                        ('error', {'type': 'aborted'}, True), ('stop', {}, False),
                                        ('error', {'type': 'provider'}, False)]:
            with self.subTest(finish=finish, error=error):
                self.assertEqual(opencode2.unfinished([user, {'type': 'assistant', 'finish': finish, 'error': error}]), expected)
        self.assertFalse(opencode2.unfinished([user, {'type': 'compaction', 'status': 'completed'}]))


class NativeContracts(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        self.task = support.running(tasks.create('steward', tasks.SYSTEM, 'inspect', 'Inspect only.', [6]),
                                    'scout', worktree=False)

    def test_v2_pins_do_not_reuse_v1_tool_names_or_erase_original_pins(self):
        legacy = [{'role': 'system', 'content': 'Original V1 harness'}, {'role': 'user', 'content': 'Original task'}]
        gateway.stable_environment(legacy, 'scout')
        old = self.task['system_context']
        native = [{'role': 'system', 'content': 'Native harness\n<cointos_native_tools>tools.cointos.task({})</cointos_native_tools>'},
                  legacy[-1]]
        shown = gateway.stable_environment(native, 'scout', 2)
        self.assertNotIn('Original V1 harness', json.dumps(shown))
        self.assertEqual(self.task['system_context'], old)
        changed = copy.deepcopy(native)
        changed[0]['content'] = changed[0]['content'].replace('Native harness', 'Incidental replacement').replace('task({})', 'check_work({})')
        shown = gateway.stable_environment(changed, 'scout', 2)
        self.assertIn('Native harness', json.dumps(shown))
        self.assertIn('check_work({})', json.dumps(shown))
        self.assertNotIn('Incidental replacement', json.dumps(shown))
        for protocol, name in [(1, 'bash'), (2, 'shell')]:
            tools = [{'type': 'function', 'function': {'name': name, 'description': name}}]
            self.assertEqual(gateway.stable_tools(tools, 'scout', protocol)[0]['function']['name'], name)
        self.assertNotEqual(self.task['tool_context'], self.task['tool_context_v2'])
        restored = state.fresh(copy.deepcopy(state.L))
        self.assertIn(self.task['system_context_v2'], restored['system_contexts'])
        self.assertIn(self.task['tool_context_v2'], restored['system_contexts'])
        public = json.dumps(frontier.inspect(self.task['id'], state.L))
        self.assertNotIn('system_context_v2', public)
        self.assertNotIn('tool_context_v2', public)

    def test_native_tool_events_keep_call_input_and_recorded_result(self):
        tools = {}
        base = {'id': 'evt_1', 'data': {'sessionID': 'ses_original', 'assistantMessageID': 'msg_original', 'id': 'call_once'}}
        opencode2.event({**base, 'type': 'session.tool.input.started', 'data': {**base['data'], 'name': 'execute'}}, tools)
        opencode2.event({**base, 'type': 'session.tool.called', 'data': {**base['data'], 'input': {'code': 'effect'}}}, tools)
        done = opencode2.event({**base, 'type': 'session.tool.success', 'data': {
            **base['data'], 'content': [{'type': 'text', 'text': 'Recorded effect'}]}}, tools)
        self.assertEqual(done['part']['tool'], 'execute')
        self.assertEqual(done['part']['state']['input'], {'code': 'effect'})
        self.assertEqual(done['part']['state']['output'], 'Recorded effect')
