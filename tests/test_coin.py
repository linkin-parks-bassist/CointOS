"""Coin's deeper-turn tool protocol."""
import copy
import io
import json
import unittest
from unittest.mock import patch

from cointos import coin


class DeepTurn(unittest.TestCase):
    def test_coin_requests_carry_the_configured_reasoning_cap(self):
        reply = {"choices": [{"message": {"role": "assistant", "content": "ready"}}]}
        captured = []
        def respond(request, **kwargs):
            captured.append(json.loads(request.data))
            return io.BytesIO(json.dumps(reply).encode())
        with patch.object(coin, "coin_key", return_value="test-key"), \
                patch.object(coin.urllib.request, "urlopen", side_effect=respond):
            coin.complete(coin.CONFIG["work_model"], [], timeout=1)
            coin.complete(coin.CONFIG["work_model"], [], timeout=1, reasoning_effort="medium")
        self.assertEqual(captured[0]["reasoning_effort"], coin.CONFIG["reasoning"]["default"])
        self.assertEqual(captured[1]["reasoning_effort"], "medium")

    def test_restart_uses_the_draining_control_and_reports_refusals(self):
        self.assertIn("restart", {t["function"]["name"] for t in coin.TOOLS})
        with patch.object(coin.cli, "restart", return_value="daemon restarted") as restart:
            self.assertEqual(coin.execute("restart", {}), {"ok": True, "output": "daemon restarted"})
            restart.assert_called_once_with()
        with patch.object(coin.cli, "restart", side_effect=SystemExit("restart cancelled: replies did not drain")):
            self.assertEqual(coin.execute("restart", {}),
                             {"ok": False, "error": "restart cancelled: replies did not drain"})

    def test_tool_results_answer_the_exact_model_call(self):
        replies = iter([
            {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call-status", "type": "function",
                "function": {"name": "status", "arguments": "{}"},
            }]},
            {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call-reply", "type": "function",
                "function": {"name": "reply", "arguments": '{"message":"All green."}'},
            }]},
        ])
        requests = []

        def complete(_model, messages, **_options):
            requests.append(copy.deepcopy(messages))
            return next(replies)

        with patch.object(coin, "complete", side_effect=complete), \
             patch.object(coin, "live_summary", return_value="green"), \
             patch.object(coin, "execute", return_value={"ok": True, "output": "green"}):
            self.assertEqual(coin.deep_turn("How is it?", [], "Checking.", None), "All green.")

        tool_result = requests[1][-1]
        self.assertEqual(tool_result["role"], "tool")
        self.assertEqual(tool_result["tool_call_id"], "call-status")
        self.assertEqual(tool_result["name"], "status")


if __name__ == "__main__":
    unittest.main()
