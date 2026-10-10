"""Coin's turn protocol: proof of life, tool identity, mid-turn messages and alerts in history."""
import copy
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from cointos import coin


def call(name, arguments=None, identifier=None):
    return {"id": identifier or f"call-{name}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments or {})}}


def assistant(*calls, content=None):
    return {"role": "assistant", "content": content, "tool_calls": list(calls)}


class Turn(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        state = patch.object(coin, "COIN_STATE", Path(directory.name))
        state.start()
        self.addCleanup(state.stop)
        self.sent = []
        sender = patch.object(coin, "send", side_effect=lambda token, chat, text: self.sent.append(text))
        sender.start()
        self.addCleanup(sender.stop)

    def run_turn(self, replies, texts=("How is it?",), arrivals=lambda: [], executed=None, knowledge=None):
        replies, requests = iter(replies), []

        def complete(_model, messages, **options):
            requests.append((copy.deepcopy(messages), options))
            return next(replies)

        with patch.object(coin, "complete", side_effect=complete), \
                patch.object(coin, "execute", side_effect=executed or (lambda name, arguments: {"ok": True, "output": "green"})):
            coin.turn("token", 7, 70, list(texts), arrivals, knowledge)
        return requests

    def test_proof_of_life_goes_out_before_the_work(self):
        requests = self.run_turn([
            assistant(call("send", {"message": "Checking."}), call("status")),
            assistant(call("send", {"message": "All green."}), call("done")),
        ])
        self.assertEqual(self.sent, ["Checking.", "All green."])
        # Every round renders alike, so each extends the state the last one left.
        self.assertEqual(requests[0][1], requests[1][1])
        self.assertTrue(requests[0][0][-1]["content"].endswith(coin.PROOF_OF_LIFE))
        self.assertEqual(requests[1][0][:len(requests[0][0])], requests[0][0])
        self.assertEqual([m["content"] for m in coin.recent(7)], ["How is it?", "Checking.", "All green."])

    def test_tool_results_answer_the_exact_model_call(self):
        requests = self.run_turn([assistant(call("status", identifier="call-7")), assistant(call("done"))])
        tool_result = requests[1][0][-1]
        self.assertEqual((tool_result["role"], tool_result["tool_call_id"], tool_result["name"]),
                         ("tool", "call-7", "status"))

    def test_the_prompt_is_fixed_and_carries_only_the_kt_tools_coin_needs(self):
        knowledge = {"names": {"kt_read", "kt_init"}, "tools": [
            {"type": "function", "function": {"name": "kt_read"}},
            {"type": "function", "function": {"name": "kt_init"}}]}
        first = self.run_turn([assistant(content="Hi.")], texts=["hello"], knowledge=knowledge)
        second = self.run_turn([assistant(content="Yes.")], texts=["still there?"], knowledge=knowledge)
        self.assertEqual(first[0][0][0], second[0][0][0])
        self.assertEqual(first[0][1]["tools"], second[0][1]["tools"])
        names = {t["function"]["name"] for t in first[0][1]["tools"]}
        self.assertIn("kt_read", names)
        self.assertNotIn("kt_init", names)

    def test_plain_content_is_sent_and_ends_the_turn(self):
        self.run_turn([assistant(content="Morning.")], texts=["hi"])
        self.assertEqual(self.sent, ["Morning."])

    def test_messages_sent_mid_turn_join_it(self):
        later = iter([["actually, pigen too"], []])
        requests = self.run_turn([
            assistant(call("send", {"message": "On it."}), call("jobs")),
            assistant(call("done")),
        ], arrivals=lambda: next(later))
        self.assertEqual(requests[1][0][-1], {"role": "user", "content": "actually, pigen too"})
        self.assertIn("actually, pigen too", [m["content"] for m in coin.recent(7)])

    def test_out_of_steps_allows_only_send_and_done(self):
        limit = coin.SETTINGS["max_tool_rounds"]
        replies = [assistant(call("jobs", {"n": n})) for n in range(limit)]
        replies += [assistant(call("halt")), assistant(call("send", {"message": "Ran long."}), call("done"))]
        executed = []
        requests = self.run_turn(replies, executed=lambda name, arguments: executed.append(name) or {"ok": True, "output": ""})
        self.assertNotIn("halt", executed)
        self.assertIn("out of steps", requests[limit + 1][0][-1]["content"])
        self.assertEqual(self.sent, ["Ran long."])

    def test_failures_are_told_plainly(self):
        refused = urllib.error.HTTPError("u", 503, "x", {}, io.BytesIO(
            b'{"error": {"message": "Qwen3.8-27B-GGUF is not running right now"}}'))
        self.assertIn("is not running right now", coin.failure(refused))
        self.assertIn("didn't answer in time", coin.failure(TimeoutError("timed out")))
        self.assertIn("`status` still works", coin.failure(RuntimeError("boom")))


class Alerts(unittest.TestCase):
    def test_forwarded_alerts_join_the_conversation(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(coin, "COIN_STATE", Path(directory)), \
                patch.object(coin, "ledger", return_value={"alerts": [{"id": 4, "text": "steward needs the user"}]}), \
                patch.object(coin.configuration, "read_json", return_value=3), \
                patch.object(coin.configuration, "write_json"), \
                patch.object(coin, "send") as send, \
                patch.object(coin.time, "sleep", side_effect=StopIteration):
            with self.assertRaises(StopIteration):
                coin.alert_forwarder("token", {7})
            self.assertEqual(coin.recent(7), [{"role": "assistant", "content": "⚠️ steward needs the user"}])
        send.assert_called_once_with("token", 7, "⚠️ steward needs the user")


class Controls(unittest.TestCase):
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

    def test_status_answers_without_the_model(self):
        with patch.object(coin, "ledger", side_effect=coin.Unreachable("lookup timed out")):
            self.assertIn("lookup timed out", coin.status_text(timeout=1.5))


if __name__ == "__main__":
    unittest.main()
