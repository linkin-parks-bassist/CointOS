"""Terminal agent commands deliver their receipt before asking the daemon to end the run."""
import os
import unittest
from unittest.mock import patch

from cointos import cli


class TerminalCommands(unittest.TestCase):
    def test_managed_dispatch_exposes_reuse_status_instead_of_only_a_task_id(self):
        result = {'ok': True, 'task': 'p:origin', 'created': False, 'status': 'blocked',
                  'message': 'Existing assignment reused; no run restarted or recovery handoff completed.'}
        for managed in (False, True):
            with self.subTest(managed=managed), patch.dict(os.environ), \
                    patch.object(cli, 'call', return_value=result), patch('builtins.print') as output:
                os.environ.pop('COINTOS_AGENT', None)
                if managed: os.environ['COINTOS_AGENT'] = 'author'
                cli.main(['agent', 'run', 'origin', 'Same assignment', '--role', 'worker', '--project', 'p'], acknowledge=False)
                text = output.call_args.args[0]
                self.assertEqual(__import__('json').loads(text) if managed else text, result if managed else 'p:origin')

    def test_revision_prints_actual_change_result(self):
        result = {'ok': True, 'item': 'p:work', 'changed': False,
                  'message': 'Assignment unchanged; no work restarted and no recovery handoff completed.'}
        with patch.object(cli, 'call', return_value=result), patch('builtins.print') as output:
            cli.main(['revise', 'p:work', 'Same assignment', '--reason', 'Preparation changed'], acknowledge=False)
        self.assertEqual(__import__('json').loads(output.call_args.args[0]), result)

    def test_correct_tests_only_retires_a_caller_with_a_checked_receipt(self):
        for has_receipt in (False, True):
            with self.subTest(receipt=has_receipt), \
                    patch.dict(cli.COMMANDS, {'correct-tests': lambda args: 'correction owner'}), \
                    patch.object(cli, 'has_receipt_here', return_value=has_receipt), \
                    patch.object(cli, 'deliver_receipt') as ack, patch('builtins.print'):
                cli.main(['correct-tests', 'p', 'tests', 'correction', 'Correct witness',
                          '--reason', 'Wrong assertion', '--summary', 'Correct the witness', '--relies-on-json', '["a"]'])
            self.assertEqual(ack.call_count, int(has_receipt))

    def test_replacement_prints_and_flushes_its_receipt_before_delivery(self):
        order = []
        receipt = {'ok': True, 'receipt': {'run': 'operator-1', 'disposition': 'complete'}}
        def call(action, body=None):
            order.append((action, body))
            return receipt
        with patch.dict(os.environ, COINTOS_TASK_ID='p:repair', COINTOS_AGENT='operator-1'), \
                patch.object(cli, 'call', side_effect=call), \
                patch.object(cli, 'has_receipt_here', return_value=True), \
                patch.object(cli, 'run_here', side_effect=AssertionError('replay needs no live run lookup')), \
                patch('builtins.print', side_effect=lambda value, **kw: order.append(('print', value, kw))):
            cli.main(['replace', 'existing'])
        self.assertEqual([entry[0] for entry in order], ['replace', 'print', 'receipt-delivered'])
        self.assertEqual(order[1][2], {'flush': True})
        self.assertEqual(__import__('json').loads(order[1][1]), receipt)

    def test_receipt_is_printed_and_flushed_before_run_retirement(self):
        order = []
        with patch.dict(os.environ, {"COINTOS_TASK_ID": "p:work", "COINTOS_AGENT": "worker-1"}), \
                patch.dict(cli.COMMANDS, {"finish": lambda args: "receipt accepted"}), \
                patch.object(cli, 'has_receipt_here', return_value=True), \
                patch("builtins.print", side_effect=lambda value, flush=False: order.append(("print", value, flush))), \
                patch.object(cli, "call", side_effect=lambda action, body=None: order.append((action, body)) or {"ok": True}):
            cli.main(["finish", "--complete", "done"])
        self.assertEqual(order, [
            ("print", "receipt accepted", True),
            ("receipt-delivered", None),
        ])

    def test_a_validation_error_that_returned_work_is_still_terminal(self):
        order = []
        recorded = {"tasks": {"p:integrate": {"receipt": {"run": "integrator-1"}}}}
        with patch.dict(os.environ, {"COINTOS_TASK_ID": "p:integrate", "COINTOS_AGENT": "integrator-1"}), \
                patch.dict(cli.COMMANDS, {"land": lambda args: (_ for _ in ()).throw(ValueError("sent back"))}), \
                patch("builtins.print", side_effect=lambda value, **kwargs: order.append(("print", value, kwargs))), \
                patch.object(cli, "ledger", return_value=recorded), \
                patch.object(cli, "call", side_effect=lambda action, body=None: order.append((action, body)) or {"ok": True}):
            cli.main(["land", "summary"])
        self.assertEqual(order, [
            ("print", "sent back", {"file": __import__("sys").stderr, "flush": True}),
            ("receipt-delivered", None),
        ])


if __name__ == "__main__":
    unittest.main()


class LiveViews(unittest.TestCase):
    def test_live_views_refuse_a_captured_shell(self):
        for command in (["view", "0"], ["watch"]):
            with patch("sys.stdin.isatty", return_value=False), patch("sys.stdout.isatty", return_value=False), \
                    patch.object(cli, "ledger", side_effect=AssertionError("must refuse before reading state")):
                with self.assertRaises(SystemExit) as refused:
                    cli.main(command)
                self.assertIn("live terminal view", str(refused.exception))


class CoinIdentityViews(unittest.TestCase):
    def test_profile_journal_and_name_reach_the_mirror(self):
        from cointos import coin_mirror
        profile = {'identity': 'synthetic', 'name': 'Synthetic Coin'}
        with patch.object(cli, 'coin_profile', return_value=profile), \
                patch.object(cli, '_coin_live_states', return_value=iter(())), \
                patch.object(coin_mirror, 'show') as show:
            cli.coin_log()
        self.assertEqual(show.call_args.args[0], cli.configuration.STATE / 'coin-synthetic/turns.jsonl')
        self.assertEqual(show.call_args.kwargs['name'], 'Synthetic Coin')

    def test_profile_live_text_never_comes_from_another_coin(self):
        profile = {'identity': 'synthetic', 'name': 'Synthetic Coin'}
        state = {'thoughts': {
            'ours': {'agent': 'coin', 'owner': 'synthetic/abc'},
            'other': {'agent': 'coin', 'owner': 'other/abc'}},
            'coin': {'busy': True, 'live': {'owner': 'other/abc', 'content': 'other text'}}}
        selected = cli.coin_view_state(state, profile)
        self.assertEqual(set(selected['thoughts']), {'ours'})
        self.assertEqual(selected['coin']['live'], {})
        state['coin']['live'] = {'owner': 'synthetic/abc', 'content': 'our text'}
        self.assertEqual(cli.coin_view_state(state, profile)['coin']['live']['content'], 'our text')
        del state['coin']['live']['owner']
        self.assertEqual(cli.coin_view_state(state, profile)['coin']['live'], {})

    def test_private_profile_refuses_before_opening_a_viewer(self):
        with patch.object(cli.coins, 'profile', return_value={
                'identity': 'synthetic', 'name': 'Private Coin', 'retain_diagnostics': False}):
            with self.assertRaisesRegex(ValueError, 'diagnostics disabled'):
                cli.coin_profile('private')

    def test_coin_command_passes_selected_profile(self):
        with patch.object(cli, 'coin_live', return_value=None) as live:
            cli.main(['coin', 'professional'], acknowledge=False)
        live.assert_called_once_with('professional')


class AutomaticCoinViews(unittest.TestCase):
    def test_automatic_slot_resolves_reported_worker_without_a_picker(self):
        from types import SimpleNamespace
        profiles = {'amateur': {'identity': 'a', 'name': 'Amateur'},
                    'professional': {'identity': 'p', 'name': 'Professional'}}
        def systemctl(args, **kwargs):
            return SimpleNamespace(returncode=0, stdout='42\n' if 'cointel-professional-coin.service' in args else '41\n')
        with patch.object(cli.coins, 'names', return_value=list(profiles)), \
                patch.object(cli.coins, 'profile', side_effect=profiles.get), \
                patch.object(cli.subprocess, 'run', side_effect=systemctl), \
                patch('builtins.input', side_effect=AssertionError('automatic viewer must never ask')):
            self.assertEqual(cli.automatic_coin_profile({'coin': {'process': {'pid': 42}}}), profiles['professional'])
            self.assertIsNone(cli.automatic_coin_profile({'coin': {}}))

    def test_slot_passes_its_identity_to_the_journal_viewer(self):
        profile = {'identity': 'synthetic', 'name': 'Synthetic'}
        with patch.object(cli, 'interactive'), \
                patch.object(cli, 'ledger', return_value={'viewers': {'0': 'coin'}, 'agents': {}}), \
                patch.object(cli, 'automatic_coin_profile', return_value=profile), \
                patch.object(cli, 'coin_profile', side_effect=AssertionError('no picker')), \
                patch.object(cli, 'coin_log', side_effect=KeyboardInterrupt) as log:
            with self.assertRaises(KeyboardInterrupt):
                cli.view(0)
        self.assertEqual(log.call_args.kwargs['profile'], profile)
