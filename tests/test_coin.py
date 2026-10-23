"""Coin's turn protocol: durable intake, tool identity, mid-turn messages and model wakes."""
import copy
import io
import json
import queue
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from cointos import coin


def call(name, arguments=None, identifier=None):
    return {"id": identifier or f"call-{name}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments or {})}}


def assistant(*calls, content=None):
    return {"role": "assistant", "content": content, "tool_calls": list(calls)}


class Delivery(unittest.TestCase):
    def test_chunks_log_only_native_success_and_correlate_without_text_or_credentials(self):
        text='Private report ' + 'x' * coin.TELEGRAM_LIMIT
        receipts=[{'message_id':31,'date':100},{'message_id':32,'date':101}]
        output=io.StringIO()
        directory=self.enterContext(tempfile.TemporaryDirectory())
        with patch.object(coin,'COIN_STATE',Path(directory)), \
                patch.object(coin,'telegram',side_effect=[OSError('retry'),*receipts]), \
                patch.object(coin.time,'sleep'), patch('sys.stdout',output):
            result=coin.deliver_text('fixture-secret-token',7,70,text)
            self.assertEqual(''.join(m['content'] for m in coin.recent(7)),text)
        records=[json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(result,receipts[-1])
        self.assertEqual([r['message_id'] for r in records],[31,32])
        self.assertNotEqual(records[0]['text_hash'],records[1]['text_hash'])
        self.assertNotIn('Private report',output.getvalue())
        self.assertNotIn('fixture-secret-token',output.getvalue())

    def test_exhausted_send_has_no_acceptance_log(self):
        output=io.StringIO()
        with patch.object(coin,'telegram',side_effect=OSError('not delivered')), \
                patch.object(coin.time,'sleep'), patch('sys.stdout',output):
            with self.assertRaises(OSError):
                coin.send('fixture',70,'Report')
        self.assertEqual(output.getvalue(),'')


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
        self.reports = []
        reporter = patch.object(coin, "report", side_effect=lambda busy, doing=None: self.reports.append((busy, doing)))
        reporter.start()
        self.addCleanup(reporter.stop)

    def run_turn(self, replies, texts=("How is it?",), arrivals=lambda: [], executed=None, knowledge=None):
        replies, requests = iter(replies), []

        def complete(_model, messages, **options):
            requests.append((copy.deepcopy(messages), options))
            return next(replies)

        with patch.object(coin, "complete", side_effect=complete), \
                patch.object(coin, "execute", side_effect=executed or (lambda name, arguments: {"ok": True, "output": "green"})):
            coin.turn("token", 7, 70, list(texts), arrivals, knowledge)
        return requests

    def test_saved_input_guidance_preserves_substantive_rounds(self):
        requests = self.run_turn([
            assistant(call("send", {"message": "Checking."}), call("status")),
            assistant(call("send", {"message": "All green."}), call("done")),
        ])
        self.assertEqual(self.sent, ["Checking.", "All green."])
        # Every round renders alike, so each extends the state the last one left.
        self.assertEqual(requests[0][1], requests[1][1])
        self.assertTrue(requests[0][0][-2]["content"].endswith(coin.INPUT_GUIDANCE))
        self.assertEqual(requests[1][0][:len(requests[0][0])], requests[0][0])
        self.assertEqual([m["content"] for m in coin.recent(7)], ["How is it?", "Checking.", "All green."])

    def test_tool_results_answer_the_exact_model_call(self):
        requests = self.run_turn([assistant(call("status", identifier="call-7")), assistant(call("done"))])
        tool_result = next(m for m in reversed(requests[1][0]) if m["role"] == "tool")
        self.assertEqual((tool_result["role"], tool_result["tool_call_id"], tool_result["name"]),
                         ("tool", "call-7", "status"))
        self.assertEqual(self.reports, [(True, "status")])

    def test_archived_captioned_receipts_are_distinct_from_pending_input_and_retries(self):
        archived = 'An earlier caption\n\n<cointos-attachments>\n{"update_id": 1, "files": [{"path": "/old/photo.jpg"}]}\n</cointos-attachments>'
        coin.remember(7, 'user', archived, at=1, input_id=1)
        text = {'id': 2, 'text': 'Quick?', 'at': 2}
        failed = self.run_turn([assistant(call('done'))], texts=[text])
        retried = self.run_turn([assistant(call('done'))], texts=[text])
        prefix = failed[0][1]['cache_prefix_messages']
        self.assertEqual(failed[0][0][:prefix], retried[0][0][:prefix])
        for request in (failed[0][0], retried[0][0]):
            history = request[1]['content']
            self.assertIn('<cointos-archived-attachments>', history)
            self.assertNotIn('<cointos-attachments>', history)
            self.assertIn('/old/photo.jpg', history)
            self.assertEqual(sum('<cointos-current-input update_id="2">' in m['content']
                                 for m in request if isinstance(m.get('content'), str)), 1)
        self.assertEqual([m['content'] for m in coin.recent(7)], [archived, 'Quick?'])

    def test_worker_clears_presence_when_knowledge_recovery_fails(self):
        inbox = queue.Queue()
        from cointos import coin_input
        coin_input.accept(coin.COIN_STATE / 'inputs', {'update_id': 1, 'message': {
            'from': {'id': 7}, 'chat': {'id': 70}, 'text': 'hello'}}, {7})
        coin_input.receipted(coin.COIN_STATE / 'inputs', 1, 71)
        inbox.put(1)
        process = unittest.mock.Mock()
        process.poll.return_value = 1
        with patch.object(coin.kt_mcp, "open_session", side_effect=[{"process": process}, RuntimeError("reopen failed")]), \
                patch.object(coin, "turn", side_effect=RuntimeError("turn failed")), \
                patch.object(coin.traceback, "print_exc"):
            with self.assertRaisesRegex(RuntimeError, "reopen failed"):
                coin.worker("token", inbox, {7})
        self.assertEqual(self.reports, [(False, None), (True, None), (False, None)])

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

    def test_internal_time_headers_are_removed_from_all_reply_routes_and_history(self):
        header = "<cointos-message-time>2026-10-15T18:33:30+00:00</cointos-message-time>\n"
        for reply in [assistant(content=header + "Ready."),
                      assistant(call("done"), content=header + "Ready."),
                      assistant(call("send", {"message": header + "Ready."}), call("done"))]:
            with self.subTest(reply=reply):
                self.run_turn([reply])
                self.assertEqual(self.sent[-1], "Ready.")
                self.assertEqual(coin.recent(7)[-1]["content"], "Ready.")

    def test_time_header_guard_preserves_quoted_examples_and_ordinary_text(self):
        header = "<cointos-message-time>unknown</cointos-message-time>"
        for text in ["The header was " + header, "```xml\n" + header + "\n```",
                     "> " + header, "<cointos-message-time>incomplete", "Morning."]:
            with self.subTest(text=text):
                self.assertEqual(coin.reply_text(text), text)
        headers = header + "\n<cointos-current-time>clock</cointos-current-time>\n"
        headers += "<cointos-message-times>timeline</cointos-message-times>\n"
        self.assertEqual(coin.reply_text(headers + "Ready."), "Ready.")
        self.run_turn([assistant(content=headers)])
        self.assertEqual(self.sent, [])
        self.assertFalse(any(m["role"] == "assistant" for m in coin.recent(7)))

    def test_closing_content_with_done_is_delivered_after_a_tool_result(self):
        self.run_turn([assistant(call("status")), assistant(call("done"), content="Paused; Qwen is running.")])
        self.assertEqual(self.sent, ["Paused; Qwen is running."])
        self.assertEqual(coin.recent(7)[-1]["content"], "Paused; Qwen is running.")

    def test_explicit_send_and_done_do_not_duplicate_closing_content(self):
        self.run_turn([assistant(call("send", {"message": "All green."}), call("done"), content="All green.")])
        self.assertEqual(self.sent, ["All green."])

    def test_failed_closing_send_is_not_recorded_as_delivered(self):
        with patch.object(coin, "send", side_effect=OSError("transport unavailable")):
            with self.assertRaises(OSError):
                self.run_turn([assistant(call("done"), content="Not delivered.")])
        self.assertFalse(any(m["role"] == "assistant" for m in coin.recent(7)))

    def test_failed_send_does_not_record_a_successful_reply(self):
        with patch.object(coin, 'send', side_effect=OSError('transport unavailable')):
            with self.assertRaises(OSError):
                self.run_turn([assistant(content='Generated but not delivered.')])
        self.assertFalse(any(m['role'] == 'assistant' for m in coin.recent(7)))
        requests = self.run_turn([assistant(content='Delivered on retry.')])
        self.assertFalse(any(m.get('content') == 'Generated but not delivered.'
                             for m in requests[0][0]))
        self.assertEqual(self.sent, ['Delivered on retry.'])
        self.assertEqual(coin.recent(7)[-1]['content'], 'Delivered on retry.')

    def test_coin_model_is_independent_of_worker_model_in_direct_and_wake_turns(self):
        with patch.dict(coin.SETTINGS, {"model": "trial-model"}), \
                patch.object(coin, "complete", return_value=assistant(content="Ready.")) as complete:
            coin.turn("token", 7, 70, ["hello"], lambda: [], None)
            coin.turn("token", 7, 70, [], lambda: [], None, wake={"message": "check"})
        self.assertEqual([request.args[0] for request in complete.call_args_list],
                         ["trial-model", "trial-model"])
        self.assertNotIn("request_class", complete.call_args_list[0].kwargs)
        self.assertEqual(complete.call_args_list[1].kwargs["request_class"], "background")

    def test_each_user_has_a_stable_opaque_cache_identity(self):
        first = self.run_turn([assistant(content="Hi.")])
        second = self.run_turn([assistant(content="Yes.")])
        with patch.object(coin, "complete", return_value=assistant(content="Hi.")) as complete:
            coin.turn("token", 8, 80, ["Hello"], lambda: [], None)
        self.assertEqual(first[0][1]["user"], second[0][1]["user"])
        self.assertNotEqual(first[0][1]["user"], complete.call_args.kwargs["user"])
        self.assertEqual(len(first[0][1]["user"]), 64)

    def test_messages_sent_mid_turn_join_it(self):
        later = iter([["actually, pigen too"], []])
        requests = self.run_turn([
            assistant(call("send", {"message": "On it."}), call("jobs")),
            assistant(call("done")),
        ], arrivals=lambda: next(later))
        self.assertEqual(requests[1][0][-1]["role"], "user")
        self.assertTrue(any(m["content"] == "actually, pigen too" and "at" in m for m in requests[1][0]))
        self.assertIn("actually, pigen too", [m["content"] for m in coin.recent(7)])

    def test_direct_and_wake_turns_get_fresh_clock_evidence_without_changing_history_or_system(self):
        first_time = datetime(2026, 10, 14, 0, 15, tzinfo=timezone.utc)
        second_time = first_time + timedelta(days=1)
        with patch.object(coin, "datetime") as clock:
            clock.now.return_value = first_time
            direct = self.run_turn([assistant(content="Ready.")], texts=["Was that event last week?"])
            clock.now.return_value = second_time
            with patch.object(coin, "complete", return_value=assistant(content="Checked.")) as complete:
                coin.turn("token", 7, 70, [], lambda: [], None, wake={"message": "check the event"})
            wake_messages = complete.call_args.args[1]
        self.assertEqual(direct[0][0][0], wake_messages[0])
        self.assertIn(first_time.astimezone().isoformat(timespec="seconds"), direct[0][0][-1]["content"])
        self.assertIn("2026-10-14T00:15:00+00:00", direct[0][0][-1]["content"])
        wake_input = next(m for m in reversed(wake_messages) if m["role"] == "user")
        self.assertIn(second_time.astimezone().isoformat(timespec="seconds"), wake_input["content"])
        self.assertTrue(any("<cointos-wake>" in (m.get("content") or "") for m in wake_messages))
        self.assertFalse(any("<cointos-current-time>" in m["content"] for m in coin.recent(7)))

    def test_out_of_steps_allows_only_send_and_done(self):
        limit = coin.SETTINGS["max_tool_rounds"]
        replies = [assistant(call("jobs", {"n": n})) for n in range(limit)]
        replies += [assistant(call("halt")), assistant(call("send", {"message": "Ran long."}), call("done"))]
        executed = []
        requests = self.run_turn(replies, executed=lambda name, arguments: executed.append(name) or {"ok": True, "output": ""})
        self.assertNotIn("halt", executed)
        self.assertIn("halt", {entry["function"]["name"] for entry in requests[limit - 1][1]["tools"]})
        for _, options in requests[limit:]:
            self.assertEqual({entry["function"]["name"] for entry in options["tools"]}, {"send", "done"})
        self.assertTrue(any("out of steps" in (m.get("content") or "").lower() for m in requests[limit + 1][0]))
        self.assertEqual(self.sent, ["Ran long."])



class Controls(unittest.TestCase):
    def test_transport_keeps_timestamps_separate_from_speech_and_tool_protocol(self):
        captured = []
        def respond(request, **kwargs):
            captured.append(json.loads(request.data))
            return io.BytesIO(json.dumps({"choices": [{"message": assistant(content="ready")}]}).encode())
        messages = [{"role": "system", "content": "fixed"},
                    {"role": "user", "content": "old request", "at": 0},
                    {**assistant(call("status", identifier="identity"),
                                  content="<cointos-message-time>old echo</cointos-message-time>\nChecking."), "at": 1},
                    {"role": "tool", "content": "green", "tool_call_id": "identity", "at": 2},
                    {"role": "user", "content": "undated"}]
        original = copy.deepcopy(messages)
        with patch.object(coin, "coin_key", return_value="fixture"), \
                patch.object(coin.urllib.request, "urlopen", side_effect=respond):
            coin.complete("fixture", messages, timeout=1)
        rendered = captured[0]["messages"]
        self.assertEqual(rendered[0], messages[0])
        self.assertEqual([m["content"] for m in rendered[1:-1]],
                         ["old request", "Checking.", "green", "undated"])
        self.assertEqual(rendered[2]["tool_calls"], messages[2]["tool_calls"])
        self.assertEqual(rendered[3]["tool_call_id"], "identity")
        self.assertEqual(rendered[-1]["role"], "user")
        for line in ["Message 2 (user): 1970-01-01T00:00:00+00:00",
                     "Message 3 (assistant): 1970-01-01T00:00:01+00:00",
                     "Message 4 (tool): 1970-01-01T00:00:02+00:00", "Message 5 (user): unknown"]:
            self.assertIn(line, rendered[-1]["content"])
        self.assertFalse(any("at" in entry for entry in rendered))
        self.assertEqual(messages, original)

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

    def test_status_tool_reads_authority_for_model_inspection(self):
        with patch.object(coin, "ledger", side_effect=coin.Unreachable("lookup timed out")):
            self.assertIn("lookup timed out", coin.status_text(timeout=1.5))


if __name__ == "__main__":
    unittest.main()
