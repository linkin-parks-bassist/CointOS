"""Agents' MCP tools: typed CLI commands without a shell, per-role catalogues, and messages
between tasks and the user."""
import json
import io
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from cointos import api, cli, client, lifecycle, mcp, opencode, queues, spawner, state
from tests import support


def direct(action, body=None, **_):
    """The client's call made in-process: as this process's agent run when it is one."""
    return api.dispatch(action, {**(body or {}), **({"caller": client.caller()} if client.caller() else {})})


class Tools(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.project = support.project(self, support.repository(self))
        self.manager = support.running(support.queued(self.project, "plan", "Plan it", kind="command"), "manager-1")
        self.enterContext(patch.object(cli, "call", direct))
        self.enterContext(patch.object(mcp, "call", direct))
        self.enterContext(patch.object(mcp, "ledger", lambda: state.L))
        self.enterContext(patch.object(cli, "ledger", lambda: state.L))
        self.enterContext(patch.dict(os.environ, COINTOS_TASK_ID=self.manager["id"], COINTOS_AGENT="manager-1"))

    def names(self, role):
        return {tool["name"] for tool in mcp.catalogue(role)}

    def test_terminal_receipt_waits_for_protocol_flush_not_internal_capture(self):
        source = support.running(support.queued(self.project, 'blocked-plan', 'Plan it', kind='command'), 'origin-run')
        api.dispatch('finish', {'caller': support.caller(source, 'origin-run'),
                               'outcome': 'blocked', 'detail': 'Use existing work'})
        lifecycle.release('origin-run', 'delivered')
        from cointos import tasks
        operator, _ = tasks.request_repair(source)
        support.running(operator, 'repair-run')
        support.queued(self.project, 'existing', 'Continue existing work')
        request = {'id': 1, 'method': 'tools/call', 'params': {'name': 'replace', 'arguments': {'children': ['existing']}}}
        order = []
        class Protocol(io.StringIO):
            def flush(self):
                order.append('flush')
                super().flush()
        protocol = Protocol()
        with patch.dict(os.environ, COINTOS_TASK_ID=operator['id'], COINTOS_AGENT='repair-run'), \
                patch.object(cli, 'deliver_receipt', side_effect=lambda: order.append('ack')):
            reply = mcp.respond(request, 'operator')
            self.assertFalse(reply['result']['isError'], reply)
            self.assertEqual(order, [])
            self.assertEqual(operator['receipt']['disposition'], 'complete')
            mcp.write_reply(protocol, request, reply)
        self.assertEqual(order, ['flush', 'ack'])
        self.assertEqual(json.loads(protocol.getvalue()), reply)

    def test_rejected_terminal_request_flushes_error_without_retiring_live_run(self):
        request = {'id': 1, 'method': 'tools/call', 'params': {'name': 'finish', 'arguments': {'complete': 'done'}}}
        (Path(self.manager['worktree']) / 'unfinished').write_text('unfinished')
        with patch.object(cli, 'deliver_receipt') as ack:
            reply = mcp.respond(request, 'manager')
            self.assertTrue(reply['result']['isError'])
            mcp.write_reply(io.StringIO(), request, reply)
        ack.assert_not_called()
        self.assertTrue(lifecycle.owns(self.manager, 'manager-1'))

    def test_failed_protocol_flush_never_acknowledges_receipt(self):
        request = {'id': 1, 'method': 'tools/call', 'params': {'name': 'replace'}}
        protocol = unittest.mock.Mock()
        protocol.flush.side_effect = BrokenPipeError('reader disappeared')
        with patch.object(cli, 'deliver_receipt') as ack, patch.object(cli, 'has_receipt_here', return_value=True):
            with self.assertRaises(BrokenPipeError):
                mcp.write_reply(protocol, request, {'result': {}})
        ack.assert_not_called()

    def test_correction_tool_acknowledges_checked_handoff_after_protocol_flush(self):
        request = {'id': 1, 'method': 'tools/call', 'params': {'name': 'correct_tests'}}
        events = []
        protocol = unittest.mock.Mock()
        protocol.flush.side_effect = lambda: events.append('flush')
        with patch.object(cli, 'has_receipt_here', return_value=True), \
                patch.object(cli, 'deliver_receipt', side_effect=lambda: events.append('ack')):
            mcp.write_reply(protocol, request, {'result': {'receipt': {'disposition': 'complete'}}})
        self.assertEqual(events, ['flush', 'ack'])

    def test_work_validation_returns_native_data_and_failure_is_a_tool_error(self):
        request={'id':1,'method':'tools/call','params':{'name':'check_work','arguments':{}}}
        checked=mcp.respond(request,'manager')['result']
        self.assertFalse(checked['isError'])
        self.assertTrue(checked['structuredContent']['completion_receipt_required'])
        (Path(self.manager['worktree'])/'uncommitted').write_text('work')
        checked=mcp.respond(request,'manager')['result']
        self.assertTrue(checked['isError'])
        self.assertFalse(checked['structuredContent']['ok'])
        self.assertEqual(json.loads(checked['content'][0]['text']),checked['structuredContent'])

    def test_structured_preview_preserves_budget_and_dependencies(self):
        arguments={'project':'p','name':'child','brief':'A bounded job','summary':'Child',
                   'dependencies':[],'generation_tokens':500}
        result={'ok':False,'problems':['specific problem']}
        with patch.object(mcp,'call',return_value=result) as called, patch.object(mcp,'unread_notice',return_value=''):
            reply=mcp.respond({'id':1,'method':'tools/call','params':{'name':'check_work','arguments':arguments}},'manager')
        self.assertEqual(called.call_args.args,('check-work',{'project':'p','name':'child','brief':'A bounded job',
                         'summary':'Child','dependencies':[],'budget':{'generation_tokens':500}}))
        self.assertTrue(reply['result']['isError'])
        self.assertEqual(reply['result']['structuredContent'],result)

    def test_malformed_tool_arguments_are_refused_without_a_request(self):
        with patch.object(mcp,'call') as called:
            reply=mcp.respond({'id':1,'method':'tools/call','params':{'name':'check_work','arguments':[]}},'manager')
        called.assert_not_called()
        self.assertTrue(reply['result']['isError'])

    def test_undeclared_preflight_target_cannot_silently_check_different_work(self):
        with patch.object(mcp, 'call') as called:
            reply = mcp.respond({'id': 1, 'method': 'tools/call', 'params': {
                'name': 'check_work', 'arguments': {'task': 'p:another-assignment'}}}, 'operator')
        called.assert_not_called()
        self.assertTrue(reply['result']['isError'])
        self.assertIn('unsupported argument(s): task', reply['result']['content'][0]['text'])
        with patch.object(mcp, 'run_cli') as run:
            output, failed = mcp.invoke('task', {'task': 'p:plan', 'invented_target': 'p:other'}, 'worker')
        run.assert_not_called()
        self.assertTrue(failed)
        self.assertIn('invented_target', output)

    def test_each_role_sees_its_own_tools(self):
        self.assertIn("queue", self.names("manager"))
        self.assertIn("land", self.names("integrator"))
        self.assertNotIn("queue", self.names("worker"))
        self.assertNotIn("land", self.names("worker"))
        self.assertTrue({"finish", "task", "send", "inbox"} <= self.names("worker"))
        self.assertEqual(mcp.invoke("land", {"summary": "x"}, "worker"), ("unknown tool 'land' for this role", True))
        self.assertIn("operator", self.names("manager"))
        self.assertIn("operator", self.names("steward"))
        self.assertNotIn("operator", self.names("worker"))
        self.assertIn('handoff', self.names('manager'))
        self.assertIn('correct_tests', self.names('manager'))
        self.assertTrue({'correct_tests', 'resume', 'replace'} <= self.names('operator'))
        self.assertFalse({'correct_tests', 'resume', 'replace', 'handoff'} & self.names('worker'))

    def test_a_brief_with_quotes_and_newlines_queues_verbatim(self):
        brief = 'Fix the "parser" isn\'t `it`\n$(rm -rf /) && echo hi'
        output, failed = mcp.invoke("queue", {"project": "p", "name": "fix", "brief": brief, "stage": "implementation",
                                              "summary": "Fix parser quoting", "dependencies": []}, "manager")
        self.assertFalse(failed, output)
        self.assertTrue(state.L["queue"]["p:fix"]["brief"].endswith(brief))
        self.assertEqual(state.L["queue"]["p:fix"]["depends"], [])

    def test_missing_arguments_are_refused_before_running(self):
        self.assertEqual(mcp.invoke("queue", {"project": "p", "name": "x"}, "manager"),
                         ("missing required argument(s): brief, summary, dependencies", True))
        self.assertTrue(mcp.invoke("finish", {}, "worker")[1])
        self.assertEqual(mcp.invoke("send", {"text": "hi"}, "worker"), ("missing required argument(s): to", True))

    def test_scout_result_is_typed_and_passes_to_cli_without_parsing_report_text(self):
        steward = next(t for t in mcp.catalogue('steward') if t['name'] == 'finish')
        self.assertIn('manager_handoff', steward['inputSchema']['properties']['scout_result']
                      ['properties']['kind']['enum'])
        worker = next(t for t in mcp.catalogue('worker') if t['name'] == 'finish')
        self.assertNotIn('scout_result', worker['inputSchema']['properties'])
        result = {'kind': 'manager_handoff', 'handoff': 'p:next'}
        with patch.object(mcp, 'run_cli', return_value=('ok', False)) as run, \
                patch.object(mcp, 'unread_notice', return_value=''):
            mcp.invoke('finish', {'complete': 'arbitrary prose', 'scout_result': result}, 'steward')
        self.assertEqual(json.loads(run.call_args.args[0][-1]), result)

    def test_protocol_lists_and_calls_tools(self):
        listed = mcp.respond({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, "manager")
        self.assertIn("queue", {tool["name"] for tool in listed["result"]["tools"]})
        called = mcp.respond({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                              "params": {"name": "task", "arguments": {"task": self.manager["id"]}}}, "manager")
        self.assertFalse(called["result"]["isError"])
        self.assertIn(self.manager["id"], called["result"]["content"][0]["text"])
        self.assertIsNone(mcp.respond({"jsonrpc": "2.0", "method": "notifications/initialized"}, "manager"))

    def test_recovery_task_shows_current_original_queue_record_after_revision_and_hold(self):
        worker = support.queued(self.project, "broken", "An incorrect assignment")
        lifecycle.fail(worker, "contract mismatch")
        with patch.object(spawner, "tree_work", return_value=[]), patch.object(spawner, "periodic", return_value=[]):
            recovery = spawner.next_task()
        self.assertEqual(recovery["kind"], "operator")
        self.assertNotEqual(recovery["id"], worker["record"])
        api.dispatch("revise", {"item": worker["id"], "brief": "Corrected assignment\nDepends on: plan",
                                "reason": "The user corrected the false premise"})
        api.dispatch("hold", {"item": worker["id"]})
        output, failed = mcp.invoke("task", {"task": recovery["id"]}, "manager")
        self.assertFalse(failed, output)
        shown = json.loads(output)
        self.assertEqual(shown["task"]["record_version"], 1, "the original failure evidence remains historical")
        self.assertEqual(shown["queue"], state.L["queue"][worker["record"]])
        self.assertEqual(shown["queue"]["version"], 2)
        self.assertEqual(shown["queue"]["held_by"], "user")
        self.assertEqual(shown["queue"]["depends"], ["plan"])

    def test_taskless_queue_inspection_still_returns_the_named_record(self):
        queues.add(self.project, "command", "undispatched", "Plan the named concern")
        shown = json.loads(cli.show_task("p:undispatched"))
        self.assertIsNone(shown["task"])
        self.assertEqual(shown["queue"], state.L["queue"]["p:undispatched"])

    def test_task_history_is_explicit_and_preserves_full_evidence(self):
        self.manager['recovery_context'] = 'PRESERVED EXECUTION EVIDENCE'
        output, failed = mcp.invoke('task', {'task': self.manager['id']}, 'manager')
        self.assertFalse(failed, output)
        self.assertNotIn('recovery_context', json.loads(output)['task'])
        output, failed = mcp.invoke('task', {'task': self.manager['id'], 'history': True}, 'manager')
        self.assertFalse(failed, output)
        self.assertEqual(json.loads(output)['task']['recovery_context'], 'PRESERVED EXECUTION EVIDENCE')

    def test_jobs_lists_states_without_repeating_whole_receipts(self):
        note = "complete: " + "verified " * 500 + "\nFULL RECEIPT DETAIL"
        self.manager["note"] = note
        output, failed = mcp.invoke("jobs", {}, "manager")
        self.assertFalse(failed, output)
        self.assertIn(self.manager["id"], output)
        self.assertIn("task for full note", output)
        self.assertNotIn("FULL RECEIPT DETAIL", output)
        self.assertEqual(len(output.splitlines()), 1)
        detail, failed = mcp.invoke("task", {"task": self.manager["id"]}, "manager")
        self.assertFalse(failed, detail)
        self.assertIn("FULL RECEIPT DETAIL", detail)
        self.assertEqual(self.manager["note"], note)

    def jobs_archive(self):
        """Old live work must remain discoverable beneath a busy settled archive."""
        worker = support.queued(self.project, "old-held", "Held assignment with complete owning evidence")
        api.dispatch("hold", {"item": worker["id"]})
        review = support.queued(self.project, "old-review", "Review the unchanged full witness")
        review["status"] = "review"
        review["receipt"] = {"disposition": "complete", "evidence": "UNABRIDGED REVIEW EVIDENCE"}
        active = [self.manager, worker, review]
        for task in active:
            task["updated_at"] = 1
        for number in range(521):
            project = "p" if number % 2 == 0 else "other"
            ident = f"{project}:archive-{number}"
            state.L["tasks"][ident] = {**self.manager, "id": ident, "place": project,
                                     "status": "done" if number % 3 else "failed", "updated_at": 100 + number,
                                     "note": "Settled historical investigation evidence " * 10}
        return active

    def test_jobs_default_keeps_old_running_held_and_review_beneath_large_archive(self):
        active = self.jobs_archive()
        output, failed = mcp.invoke("jobs", {}, "manager")
        self.assertFalse(failed, output)
        rows = output.splitlines()
        shown = {row.split()[1] for row in rows}
        self.assertEqual(len(rows), 33, "complete unfinished frontier plus existing thirty-record history")
        for task in active:
            self.assertIn(task["id"], shown)
        self.assertIn("p:archive-520", shown)
        self.assertNotIn("p:archive-0", shown)
        all_output, failed = mcp.invoke("jobs", {"all": True}, "manager")
        self.assertFalse(failed, all_output)
        self.assertEqual({row.split()[1] for row in all_output.splitlines()}, set(state.L["tasks"]))
        self.assertLess(len(output), len(all_output) // 10, "discovery avoids a full historical prompt tail")
        held, failed = mcp.invoke("task", {"task": active[1]["id"]}, "manager")
        self.assertFalse(failed, held)
        self.assertEqual(json.loads(held)["queue"]["held_by"], "user")
        self.assertEqual(json.loads(held)["queue"]["brief"], active[1]["brief"])
        inspected, failed = mcp.invoke("task", {"task": active[2]["id"]}, "manager")
        self.assertFalse(failed, inspected)
        self.assertEqual(json.loads(inspected)["task"]["receipt"], active[2]["receipt"])

    def test_jobs_project_filter_precedes_recent_window_and_explicit_history(self):
        active = self.jobs_archive()
        # Similar project names cannot match accidentally; system tasks are not
        # project work merely because their IDs contain a matching substring.
        for place in ("p-extra", "system"):
            task = {**self.manager, "id": f"{place}:live", "place": place, "updated_at": 900}
            state.L["tasks"][task["id"]] = task
        output, failed = mcp.invoke("jobs", {"project": "p"}, "worker")
        self.assertFalse(failed, output)
        shown = {row.split()[1] for row in output.splitlines()}
        self.assertEqual(len(shown), 33)
        self.assertTrue({task["id"] for task in active} <= shown)
        self.assertTrue(all(state.L["tasks"][ident]["place"] == "p" for ident in shown))
        self.assertIn("p:archive-462", shown, "history window is applied after exact project filtering")
        all_output, failed = mcp.invoke("jobs", {"project": "p", "all": True}, "integrator")
        self.assertFalse(failed, all_output)
        self.assertEqual({row.split()[1] for row in all_output.splitlines()},
                         {task["id"] for task in state.L["tasks"].values() if task["place"] == "p"})
        empty, failed = mcp.invoke("jobs", {"project": "absent"}, "manager")
        self.assertFalse(failed, empty)
        self.assertEqual(empty, "no tasks yet")

    def test_messages_reach_an_active_task_and_announce_themselves(self):
        worker = support.running(support.queued(self.project, "build"), "worker-1")
        self.assertEqual(mcp.invoke("send", {"to": worker["id"], "text": "Use the memo API"}, "manager"),
                         (f"sent to {worker['id']}", False))
        with patch.dict(os.environ, COINTOS_TASK_ID=worker["id"], COINTOS_AGENT="worker-1"):
            output, _ = mcp.invoke("task", {"task": worker["id"]}, "worker")
            self.assertIn("[1 unread message: call inbox]", output)
            self.assertEqual(mcp.invoke("inbox", {}, "worker"), (f"From {self.manager['id']}:\nUse the memo API", False))
            self.assertNotIn("unread", mcp.invoke("task", {"task": worker["id"]}, "worker")[0])

    def test_messages_need_a_live_sender_and_an_active_recipient(self):
        self.assertTrue(mcp.invoke("send", {"to": "p:nothing", "text": "hi"}, "manager")[1])
        with patch.dict(os.environ, COINTOS_AGENT="stale-run"):
            self.assertTrue(mcp.invoke("send", {"to": self.manager["id"], "text": "hi"}, "manager")[1])

    def test_the_user_can_message_an_agent_and_agents_can_reach_the_user(self):
        with patch.dict(os.environ, {"COINTOS_TASK_ID": "", "COINTOS_AGENT": ""}):
            self.assertEqual(api.dispatch("send", {"to": self.manager["id"], "text": "Prioritise tests"})["to"], self.manager["id"])
        self.assertIn("From user:\nPrioritise tests", mcp.invoke("inbox", {}, "manager")[0])
        with patch.object(api, "alert") as alert:
            mcp.invoke("send", {"to": "user", "text": "Need a decision"}, "manager")
        alert.assert_called_once_with(f"Message from {self.manager['id']}: Need a decision")

    def test_peers_show_other_runs_their_purpose_activity_and_changes(self):
        self.assertEqual(mcp.invoke("peers", {}, "manager")[0], "no other agents are running")
        worker = support.running(support.queued(self.project, "build", "Summary: Builds the parser front end.\nDo it"), "worker-1")
        worker["base_commit"] = support.git.head(worker["worktree"])
        (Path(worker["worktree"]) / "parser.c").write_text("int parse(void);\n")
        support.git.run(worker["worktree"], "add", "parser.c")
        state.L["agents"]["worker-1"]["doing"] = "edit: parser.c"
        output, failed = mcp.invoke("peers", {}, "manager")
        self.assertFalse(failed)
        self.assertIn(f"{worker['id']} (worker, running): Builds the parser front end.", output)
        self.assertIn("now: edit: parser.c", output)
        self.assertIn("parser.c", output.split("changed:")[1])
        self.assertNotIn(self.manager["id"] + " (", output)

    def test_external_mailbox_receives_without_phone_alerts_and_replies_as_itself(self):
        with patch.object(api, "alert") as alert:
            result, failed = mcp.invoke("send", {"to": "mailbox:codex", "text": "Hello Codex"}, "manager")
            self.assertFalse(failed, result)
            alert.assert_not_called()
        self.assertFalse(state.L["messages"][-1]["read"])
        with patch.dict(os.environ, COINTOS_TASK_ID="", COINTOS_AGENT=""):
            self.assertIn("Hello Codex", cli.COMMANDS["inbox"](cli.parser().parse_args(["inbox", "--mailbox", "codex"])))
            self.assertEqual(api.dispatch("inbox", {"mailbox": "codex"})["messages"], [])
            api.dispatch("send", {"mailbox": "codex", "to": self.manager["id"], "text": "Hello back"})
        self.assertIn("From mailbox:codex:\nHello back", mcp.invoke("inbox", {}, "manager")[0])

    def test_task_cannot_impersonate_or_read_external_mailbox(self):
        with self.assertRaises(api.ApiError):
            api.dispatch("inbox", {"caller": support.caller(self.manager, "manager-1"), "mailbox": "codex"})
        for target in ("mailbox:", "mailbox:bad/name", "mailbox:bad name"):
            self.assertTrue(mcp.invoke("send", {"to": target, "text": "hi"}, "manager")[1])

    def test_a_message_is_posted_once_into_the_recipients_live_session(self):
        from cointos import messages
        posted = []

        class Inline:  # the fixtures replace threading.Thread; deliver synchronously instead
            def __init__(self, target, args, daemon):
                self.run = lambda: target(*args)

            def start(self):
                self.run()

        self.enterContext(patch.object(messages.threading, "Thread", Inline))
        self.enterContext(patch.object(messages, "post", lambda *call: posted.append(call)))
        worker = support.running(support.queued(self.project, "build"), "worker-1")
        mcp.invoke("send", {"to": worker["id"], "text": "Use the memo API"}, "manager")
        messages.pending()  # no live session yet: the message waits
        self.assertEqual((posted, state.L["messages"][-1]["read"]), ([], False))
        state.L["agents"]["worker-1"].update(url="http://127.0.0.1:9", session="ses_1")
        messages.pending()
        messages.pending()
        self.assertEqual(posted, [("http://127.0.0.1:9", "ses_1", worker["worktree"],
                                   f'<message from="{self.manager["name"]} ({self.manager["id"]})">\nUse the memo API\n</message>')])
        self.assertTrue(state.L["messages"][-1]["read"])

    def test_a_failed_post_is_retried_later(self):
        from cointos import messages

        class Inline:
            def __init__(self, target, args, daemon):
                self.run = lambda: target(*args)

            def start(self):
                self.run()

        self.enterContext(patch.object(messages.threading, "Thread", Inline))
        attempts = []

        def flaky(*call):
            attempts.append(call)
            if len(attempts) == 1:
                raise OSError("connection refused")

        self.enterContext(patch.object(messages, "post", flaky))
        worker = support.running(support.queued(self.project, "build"), "worker-1")
        state.L["agents"]["worker-1"].update(url="http://127.0.0.1:9", session="ses_1")
        mcp.invoke("send", {"to": worker["id"], "text": "Hello"}, "manager")
        messages.pending()
        self.assertFalse(state.L["messages"][-1]["read"])
        messages.pending()
        self.assertEqual((len(attempts), state.L["messages"][-1]["read"]), (2, True))

    def test_every_task_gets_its_own_generated_name_for_life(self):
        from cointos import names, prompts
        worker = support.queued(self.project, "build")
        self.assertRegex(worker["name"], r"^[A-Z][a-z]{2,7}$")
        self.assertNotEqual(worker["name"], self.manager["name"])
        self.assertIn(f"Your name is {worker['name']}.", prompts.identity(worker))
        taken = {f"Name{i}" for i in range(50)} | {"Rako"}
        import random
        rng = random.Random(3)
        made = {names.invent(taken, rng) for _ in range(200)}
        self.assertEqual(len(made & {n.lower() for n in taken}), 0)
        self.assertGreater(len(made), 150, "names rarely collide")

    def test_agents_get_the_cointos_server_in_their_config(self):
        server = opencode.settings(state.CONFIG, "key", {"id": "p:x", "abilities": ["standard"]}, [], "worker-9")["mcp"]["cointos"]
        self.assertEqual(server["command"][-2:], ["-m", "cointos.mcp"])
        self.assertEqual((server["environment"]["COINTOS_TASK_ID"], server["environment"]["COINTOS_AGENT"]), ("p:x", "worker-9"))
        self.assertGreater(server['timeout'],
                           (state.CONFIG['timeouts']['validation_seconds'] + state.CONFIG['timeouts']['api_seconds']) * 1000)
        json.dumps(server)
