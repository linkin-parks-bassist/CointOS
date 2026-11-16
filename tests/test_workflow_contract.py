"""Only the currently running MCP server can refresh its owned operational instructions."""
import copy
import json
import unittest

from cointos import gateway, mcp, state, tasks
from tests import support


class WorkflowContract(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        self.task = support.running(tasks.create('steward', tasks.SYSTEM, 'inspect', 'Inspect only.', [6]),
                                    'scout', worktree=False)

    def block(self, text):
        return '<server name="cointos">' + text + '</server>'

    def messages(self, contract=None):
        content = 'Project rule: preserve every required behavior.\nLegacy procedure: Git commit before finishing.'
        if contract:
            content += '\n<mcp_instructions>' + self.block(contract) + '</mcp_instructions>'
        return [{'role': 'system', 'content': content}, {'role': 'user', 'content': 'Original task and history.'}]

    def test_current_mcp_contract_refreshes_retained_prefix_without_rewriting_history_or_project_rules(self):
        original = self.messages()
        first = gateway.stable_environment(original, 'scout')
        previous = self.task['system_context']
        current = mcp.respond({'id': 1, 'method': 'initialize'}, 'steward')['result']['instructions']
        incoming = self.messages(current)
        retained = copy.deepcopy(incoming)
        shown = gateway.stable_environment(incoming, 'scout')
        self.assertEqual(incoming, retained)
        self.assertEqual(shown[0], first[0], 'project instructions and requirements stay pinned')
        self.assertEqual(shown[1], {'role': 'system', 'content': self.block(current)})
        self.assertEqual(shown[2], original[1])
        self.assertNotEqual(self.task['system_context'], previous)
        self.assertEqual(json.loads(state.L['system_contexts'][self.task['system_context']]), shown[:2])
        self.assertEqual(gateway.stable_environment(incoming, 'scout'), shown)

    def test_only_owned_section_changes_when_handler_contract_changes(self):
        first = gateway.stable_environment(self.messages('Current first contract.'), 'scout')
        changed = self.messages('Current replacement contract.')
        changed[0]['content'] = changed[0]['content'].replace('preserve every required behavior', 'Changed incidental prose')
        shown = gateway.stable_environment(changed, 'scout')
        self.assertEqual(shown[0], first[0])
        self.assertEqual(shown[1]['content'], self.block('Current replacement contract.'))
        self.assertNotIn('Current first contract.', json.dumps(shown))
        self.assertNotIn('Changed incidental prose', json.dumps(shown))

    def test_old_mcp_without_owned_instructions_does_not_receive_a_new_daemon_contract(self):
        original = self.messages()
        shown = gateway.stable_environment(original, 'scout')
        self.assertEqual(len(shown), 2)
        self.assertNotIn('Current CointOS workflow', json.dumps(shown))
        # Tool-free compaction/fallback must retain the last established handler contract.
        current = gateway.stable_environment(self.messages('Known current handler.'), 'scout')
        fallback = gateway.stable_environment([original[-1]], 'scout')
        self.assertEqual(fallback[:-1], current[:-1])

    def test_conflicting_owned_blocks_refuse_without_mutating_authority(self):
        original = gateway.stable_environment(self.messages(), 'scout')
        digest = self.task['system_context']
        conflicting = [{'role': 'system', 'content': self.block('first') + self.block('second')}]
        with self.assertRaisesRegex(ValueError, 'conflicting CointOS workflow instructions'):
            gateway.stable_environment(conflicting, 'scout')
        self.assertEqual(self.task['system_context'], digest)
        self.assertEqual(gateway.stable_environment(self.messages(), 'scout'), original)

    def test_user_and_coin_prefixes_are_not_rewritten(self):
        for identity in ('user', 'coin'):
            messages = self.messages('Current handler contract.')
            self.assertIs(gateway.stable_environment(messages, identity), messages)
