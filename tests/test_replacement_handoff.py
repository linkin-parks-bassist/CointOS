"""Recovery replacement closes its checked handoff without a second model turn."""
import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from cointos import api, git, lifecycle, state
from tests import support
from tests import test_operator_handback as handback


class ReplacementHandoff(unittest.TestCase):
    setUp = handback.OperatorHandback.setUp
    direct = handback.OperatorHandback.direct
    call = handback.OperatorHandback.call
    blocked = handback.OperatorHandback.blocked
    repair = handback.OperatorHandback.repair

    def fixture(self, child_brief='Continue existing work'):
        source = self.blocked()
        operator = self.repair(source)
        child = support.queued(self.project, 'child', child_brief)
        consumer = support.running(support.queued(self.project, 'consumer', 'Use result\nDepends on: origin'),
                                   'consumer-run')
        return source, operator, child, consumer

    def refused_unchanged(self, operator, pattern):
        before = copy.deepcopy(state.L)
        with patch.object(lifecycle, 'stop') as stop, self.assertRaisesRegex(ValueError, pattern):
            self.call(operator, 'replace', children=['child'])
        stop.assert_not_called()
        self.assertEqual(state.L, before)

    def test_handoff_repoints_live_consumers_and_records_receipt_in_one_request(self):
        source, operator, child, consumer = self.fixture()
        before = set(state.L['queue'])
        result = self.call(operator, 'replace', children=['child'])
        self.assertEqual(set(state.L['queue']), before)
        self.assertEqual(state.L['queue'][source['record']]['replaced_by'], ['child'])
        record = state.L['queue'][consumer['record']]
        self.assertEqual(record['depends'], ['child'])
        self.assertIn('Depends on: child', consumer['brief'])
        self.assertEqual((consumer['status'], consumer['record_version']), ('waiting', record['version']))
        receipt = result['receipt']
        self.assertEqual((operator['status'], receipt['run'], receipt['disposition']),
                         ('done', 'repair-run', 'complete'))
        self.assertEqual(receipt['evidence']['replacement'], ['child'])
        self.assertEqual(receipt['evidence']['repaired_record'], source['record'])
        self.assertIsNone(source.get('acceptance'))
        self.assertIsNone(child.get('acceptance'))
        self.assertNotIn('done', state.L['queue'][source['record']])
        # Exhaustion racing the response cannot turn a checked handoff into failure.
        lifecycle.retry_fresh('repair-run', 'budget exhausted', 'last output')
        self.assertEqual((operator['status'], operator['receipt']), ('done', receipt))

    def test_exact_lost_response_replays_after_retirement_and_other_requests_refuse(self):
        source, operator, child, consumer = self.fixture()
        body = {'children': ['child'], 'caller': support.caller(operator, 'repair-run')}
        first = api.dispatch('replace', body)
        lifecycle.release('repair-run', 'delivered')
        before = copy.deepcopy(state.L)
        self.assertEqual(api.dispatch('replace', body), first)
        for name in ('queue', 'tasks', 'agents'):
            self.assertEqual(state.L[name], before[name])
        before = copy.deepcopy(state.L)
        for extra in ({'children': ['consumer']}, {'caller': support.caller(operator, 'foreign-run')}):
            with self.assertRaises(ValueError):
                api.dispatch('replace', {**body, **extra})
        self.assertEqual(state.L, before)

    def test_invalid_dependency_closure_leaves_graph_tasks_and_runs_untouched(self):
        source, operator, child, consumer = self.fixture('Existing work\nDepends on: missing')
        self.refused_unchanged(operator, 'unknown|dependency')

    def test_held_child_cannot_authorize_handoff(self):
        source, operator, child, consumer = self.fixture()
        api.dispatch('hold', {'item': child['record']})
        self.refused_unchanged(operator, 'held')

    def test_foreign_origin_hold_cannot_be_bypassed(self):
        source, operator, child, consumer = self.fixture()
        state.L['queue'][source['record']]['held_by'] = 'user'
        self.refused_unchanged(operator, 'controllable|held')

    def test_dirty_or_unlanded_operator_artifacts_refuse_before_any_repoint(self):
        source, operator, child, consumer = self.fixture()
        (Path(operator['worktree']) / 'repair-note').write_text('Checked repair evidence.\n')
        self.refused_unchanged(operator, 'uncommitted')
        commit = support.commit(operator['worktree'])
        self.refused_unchanged(operator, 'land|merge')
        git.publish(self.project['path'], 'main', commit, git.head(self.project['path'], 'main'))
        result = self.call(operator, 'replace', children=['child'])
        self.assertEqual(result['receipt']['evidence']['commit'], commit)

    def test_validating_consumer_refuses_before_graph_or_run_changes(self):
        source, operator, child, consumer = self.fixture()
        consumer['validating'] = True
        self.refused_unchanged(operator, 'validated')

    def test_self_or_foreign_replacement_refuses_without_receipt(self):
        source, operator, child, consumer = self.fixture()
        before = copy.deepcopy(state.L)
        for children in (['origin'], ['q:child'], []):
            with self.assertRaises(ValueError):
                self.call(operator, 'replace', children=children)
        self.assertEqual(state.L, before)
