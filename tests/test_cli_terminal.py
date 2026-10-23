"""Terminal agent commands deliver their receipt before asking the daemon to end the run."""
import os
import unittest
from unittest.mock import patch

from cointos import cli


class TerminalCommands(unittest.TestCase):
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
