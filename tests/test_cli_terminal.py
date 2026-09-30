"""Terminal agent commands deliver their receipt before asking the daemon to end the run."""
import os
import unittest
from unittest.mock import patch

from cointos import cli


class TerminalCommands(unittest.TestCase):
    def test_receipt_is_printed_and_flushed_before_run_retirement(self):
        order = []
        with patch.dict(os.environ, {"COINTOS_TASK_ID": "p:work", "COINTOS_AGENT": "worker-1"}), \
                patch.dict(cli.COMMANDS, {"finish": lambda args: "receipt accepted"}), \
                patch("builtins.print", side_effect=lambda value, flush=False: order.append(("print", value, flush))), \
                patch.object(cli, "call", side_effect=lambda action, body: order.append((action, body)) or {"ok": True}):
            cli.main(["finish", "--complete", "done"])
        self.assertEqual(order, [
            ("print", "receipt accepted", True),
            ("receipt-delivered", {"task": "p:work", "run": "worker-1"}),
        ])

    def test_a_validation_error_that_returned_work_is_still_terminal(self):
        order = []
        recorded = {"tasks": {"p:integrate": {"receipt": {"run": "integrator-1"}}}}
        with patch.dict(os.environ, {"COINTOS_TASK_ID": "p:integrate", "COINTOS_AGENT": "integrator-1"}), \
                patch.dict(cli.COMMANDS, {"land": lambda args: (_ for _ in ()).throw(ValueError("sent back"))}), \
                patch("builtins.print", side_effect=lambda value, **kwargs: order.append(("print", value, kwargs))), \
                patch.object(cli, "ledger", return_value=recorded), \
                patch.object(cli, "call", side_effect=lambda action, body: order.append((action, body)) or {"ok": True}):
            cli.main(["land", "summary"])
        self.assertEqual(order, [
            ("print", "sent back", {"file": __import__("sys").stderr, "flush": True}),
            ("receipt-delivered", {"task": "p:integrate", "run": "integrator-1"}),
        ])


if __name__ == "__main__":
    unittest.main()
