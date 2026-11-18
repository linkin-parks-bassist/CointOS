import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cointos import coin, coin_reports
from tests.test_coin import assistant, call


class ResultDelivery(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(coin, 'COIN_STATE', self.root))
        self.enterContext(patch.object(coin, 'report'))
        self.sent = []
        self.enterContext(patch.object(coin, 'send', side_effect=lambda token, chat, text: self.sent.append(text)))

    def run_completion(self, replies, arrivals=lambda: [], wake=None):
        captured = []
        replies = iter(replies)
        def complete(*args, **kwargs):
            captured.append(copy.deepcopy(args[1]))
            return next(replies)
        with patch.object(coin, 'complete', side_effect=complete):
            coin.turn('fixture', 7, 70, [], arrivals, None,
                      wake=wake or {'message': 'Report completion of requested work. Wire the CLI.'})
        return captured

    def report(self, evidence=('check',), message='The CLI is wired.'):
        return call('report_result', {'location': str(self.root), 'milestone': 'CLI wiring',
                    'message': message, 'evidence_calls': list(evidence)})

    def check(self):
        # A real file read, with no Telegram or model inference in this fixture.
        path = self.root / 'implementation.c'
        path.write_text('int main(void) { return structured_compile(); }\n')
        item = call('fs_read', {'path': str(path)})
        item['id'] = 'check'
        return item

    def test_result_contains_an_id_the_model_can_read_and_cite(self):
        import json
        check = self.check()
        check['id'] = 'opaque-native-call-71'
        rounds = iter([0, 1, 2])
        def complete(_model, messages, **kwargs):
            step = next(rounds)
            if step == 0:
                return assistant(check)
            if step == 1:
                # The model can read result text, even when its chat template hides call IDs.
                result = json.loads(next(m['content'] for m in reversed(messages) if m['role'] == 'tool'))
                return assistant(self.report(evidence=[result['evidence_call_id']]))
            return assistant(call('done'))
        with patch.object(coin, 'complete', side_effect=complete):
            coin.turn('fixture', 7, 70, [], lambda: [], None,
                      wake={'message': 'Report completion of requested work. Wire the CLI.'})
        self.assertEqual(self.sent, ['The CLI is wired.'])

    def test_completion_wake_cannot_bypass_verification_with_send_or_closing_prose(self):
        captured = self.run_completion([
            assistant(call('send', {'message': 'Done and verified!'})),
            assistant(call('done'), content='Done and verified!')])
        self.assertEqual(self.sent, [])
        self.assertIn('Use report_result', captured[1][-2]['content'])
        self.run_completion([assistant(content='Done and verified!'), assistant(call('done'))])
        self.assertEqual(self.sent, [])
        self.run_completion([assistant(call('send', {'message': 'Another victory lap'}), call('done'))],
                            wake={'message': 'Check the wiring task.',
                                  'condition': {'kind': 'task-state', 'state': 'done'}})
        self.assertEqual(self.sent, [])

    def test_missing_and_failed_verification_refuse_result(self):
        captured = self.run_completion([
            assistant(self.report()), assistant(call('done'))])
        self.assertEqual(self.sent, [])
        self.assertIn('successful fs_read/run_command', captured[1][-2]['content'])
        bad = call('run_command', {'command': 'exit 1'})
        bad['id'] = 'check'
        self.run_completion([assistant(bad), assistant(self.report()), assistant(call('done'))])
        self.assertEqual(self.sent, [])

    def test_repeat_result_across_turns_and_history_rollover_sends_once(self):
        self.run_completion([assistant(self.check()), assistant(self.report(), call('done'), content='Duplicate closing prose')])
        for i in range(30):
            coin.remember(7, 'assistant', f'Unrelated reply {i}')
        captured = self.run_completion([
            assistant(self.check()), assistant(self.report(message='Rephrased victory lap'), call('done'))])
        self.assertEqual(self.sent, ['The CLI is wired.'])
        context = next(m['content'] for m in captured[0] if m['content'].startswith('<cointos-reported-results>'))
        self.assertIn('The CLI is wired.', context)
        self.assertEqual(len(coin_reports.context(self.root / 'reports', 7, 70)), 1)
        self.assertEqual(coin_reports.context(self.root / 'reports', 8, 70), [])
        self.assertEqual(coin_reports.context(self.root / 'reports', 7, 71), [])

    def test_reporting_periods_are_distinct_but_same_period_replay_is_suppressed(self):
        for week in ('2026-11-09', '2026-11-16', '2026-11-16'):
            report = self.report(message=f'Report for {week}')
            import json
            args = json.loads(report['function']['arguments'])
            args['milestone'] = f'weekly-report-{week}'
            report['function']['arguments'] = json.dumps(args)
            self.run_completion([assistant(self.check()), assistant(report, call('done'))],
                                wake={'message': 'Prepare the report for the current week.',
                                      'condition': {'kind': 'schedule'}})
        self.assertEqual(self.sent, ['Report for 2026-11-09', 'Report for 2026-11-16'])

    def test_report_whose_stored_key_predates_a_directory_rename_stays_readable_and_deduplicated(self):
        import json
        directory = self.root / 'reports'
        directory.mkdir(mode=0o700)
        item = {'user': 7, 'chat': 70, 'location': str(self.root.resolve()), 'milestone': 'cli-wiring',
                'message': 'The CLI is wired.', 'evidence': [{'call': 'check'}], 'at': 1.0}
        stale = coin_reports.identity(7, 70, '/renamed/before', 'cli-wiring')
        path = directory / 'reports.json'
        path.write_text(json.dumps({'version': 1, 'reports': {stale: item}}))
        path.chmod(0o600)
        self.assertEqual(coin_reports.context(directory, 7, 70), [item])
        self.run_completion([assistant(self.check()), assistant(self.report(message='Again'), call('done'))])
        self.assertEqual(self.sent, [])
        self.assertEqual(len(coin_reports.context(directory, 7, 70)), 1)

    def test_failed_delivery_does_not_retire_result(self):
        with patch.object(coin, 'send', side_effect=OSError('offline')):
            with self.assertRaises(OSError):
                self.run_completion([assistant(self.check()), assistant(self.report(), call('done'))])
        self.assertEqual(coin_reports.context(self.root / 'reports', 7, 70), [])
        self.run_completion([assistant(self.check()), assistant(self.report(), call('done'))])
        self.assertEqual(self.sent, ['The CLI is wired.'])

    def test_new_direct_question_during_completion_wake_can_get_normal_answer(self):
        arrivals = iter([['What is happening?']])
        self.run_completion([
            assistant(call('fs_stat', {'path': str(self.root)})),
            assistant(call('send', {'message': 'The CLI is wired; pipeline work remains.'}), call('done'))],
            arrivals=lambda: next(arrivals, []))
        self.assertEqual(self.sent, ['The CLI is wired; pipeline work remains.'])

    def test_completion_checks_cannot_rearm_product_supervision(self):
        with patch.object(coin, 'invoke') as invoke:
            captured = self.run_completion([
                assistant(call('wake', {'message': 'Inspect queue again', 'condition': {
                    'kind': 'task-state', 'task': 'p:next', 'state': 'done'}})),
                assistant(call('done'))])
        invoke.assert_not_called()
        self.assertIn('service observes factory handoffs', captured[1][-2]['content'])
        self.assertEqual(self.sent, [])
