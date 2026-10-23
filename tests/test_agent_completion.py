"""Receipt-driven completion: one typed receipt per run; process exit only reconciles."""
import json
import os
import secrets
import subprocess
import sys
import io
from types import SimpleNamespace
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cointos import api, checks, frontier, git, lifecycle, opencode, prompts, queues, runs, schema, snapshots, spawner, state, tasks, trees
from tests import support


class RunObserver(unittest.TestCase):
    def test_malformed_event_shapes_do_not_end_a_live_run_or_hide_later_valid_events(self):
        support.fresh_ledger(self)
        support.quiet(self)
        malformed = [None, [], 4, "bad event", {"part": ["bad part"]},
                     {"part": {"type": "text", "text": 7}},
                     {"part": {"type": "tool", "state": 7}},
                     {"part": {"type": "tool", "state": {"input": "bad input"}}},
                     {"part": {"type": "tool", "state": {"input": ["bad input"]}}}]
        for index, event in enumerate(malformed):
            with self.subTest(event=event), tempfile.TemporaryDirectory() as root:
                agent = "shape-run-" + str(index)
                task = support.running(tasks.create("steward", tasks.SYSTEM, "inspect-" + str(index),
                                                     "Inspect malformed event", [6]), agent)
                directory = Path(root)
                session = "valid-session-" + str(index)
                (directory / "events.jsonl").write_text(json.dumps(event) + "\n" + json.dumps({
                    "type": "text", "sessionID": session, "part": {"type": "text", "text": "Still running"}}) + "\n")
                (directory / "exit.json").write_text(json.dumps({"code": 1}))
                observed = []

                def unit_state(*args):
                    observed.append(None)
                    self.assertTrue(lifecycle.owns(task, agent))
                    if len(observed) > 1:
                        self.assertEqual(task["session"], session)
                    return len(observed) == 1

                with patch.object(opencode, "run_dir", return_value=directory), \
                        patch.object(opencode, "active", side_effect=unit_state), patch.object(opencode.time, "sleep"):
                    runs.follow(agent, None, None)
                self.assertEqual(len(observed), 2, "malformed telemetry cannot settle a live run")
                self.assertEqual((task["status"], task["session"]), ("waiting", session))
                self.assertNotIn("AttributeError", task["note"])

    def test_recovery_evidence_keeps_valid_outward_and_tool_records_among_malformed_events(self):
        malformed = [None, [], 4, {"part": ["bad"]}, {"part": {"type": "text", "text": 7}},
                     {"part": {"type": "tool", "state": "bad"}}]
        outward = {"part": {"type": "text", "text": "Validated the existing contract"}}
        tool = {"part": {"type": "tool", "tool": "shell", "state": {"status": "completed",
                "input": {"command": "verify contract"}, "output": "All checks passed"}}}
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            transcript = [outward, *malformed, tool, *malformed]
            (directory / "events.jsonl").write_text("\n".join(json.dumps(event) for event in transcript) + "\n")
            with patch.object(opencode, "run_dir", return_value=directory):
                evidence = opencode.evidence("recovery-transcript", 10)
            self.assertEqual(evidence, ["TOOL: shell {'command': 'verify contract'}\nRESULT: All checks passed",
                                        "OUTWARD: Validated the existing contract"])

    def test_runner_stops_its_server_even_when_metadata_publication_fails(self):
        for artifact in ("server.json", "exit.json"):
            with self.subTest(artifact=artifact), tempfile.TemporaryDirectory() as root:
                directory = Path(root)
                (directory / "run.json").write_text(json.dumps({"task": {"worktree": root}, "session": None,
                    "command": ["opencode", "run"], "text": "Inspect fixture", "model": {}}))
                server = SimpleNamespace(pid=123)
                client = SimpleNamespace(stdin=io.BytesIO(), wait=lambda: 1)
                original_write = opencode.write_json

                def publish(path, value):
                    if path.name == artifact:
                        raise OSError("fixture metadata publication failed: " + artifact)
                    original_write(path, value)

                with patch.object(opencode, "environment", return_value={}), \
                        patch.object(opencode, "start_server", return_value=(server, "http://fixture")), \
                        patch.object(opencode, "stop_group") as stop, \
                        patch.object(opencode.subprocess, "Popen", return_value=client), \
                        patch.object(opencode, "write_json", side_effect=publish):
                    with self.assertRaisesRegex(OSError, "fixture metadata publication failed"):
                        opencode.serve_run(directory)
                    stop.assert_called_once_with(server.pid)

    def test_runner_json_publication_does_not_reconcile_a_live_producer_mid_write(self):
        support.fresh_ledger(self)
        support.quiet(self)
        task = support.running(tasks.create("steward", tasks.SYSTEM, "inspect", "Inspect publication", [6]), "json-run")
        state.L["agents"]["json-run"]["engaged"] = True
        actual_write = Path.write_text
        actual_replace = os.replace
        observed = []
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            actual_write(directory / "run.json", json.dumps({"task": {"worktree": root}, "session": None,
                "command": ["opencode", "run"], "text": "Observe the fixture", "model": {}}))

            def inspect_nonterminal():
                # End only this observer after its first nonterminal poll; the unit
                # and its lifecycle ownership remain live throughout the interleaving.
                with patch.object(opencode, "active", return_value=True), \
                        patch.object(opencode.time, "sleep", side_effect=runs.Ended):
                    runs.follow("json-run", None, None)
                observed.append("server publication")
                self.assertTrue(lifecycle.owns(task, "json-run"), "partial artifacts cannot stop their live producer")

            def direct_write(path, value, *args, **kwargs):
                if path == directory / "server.json":
                    with path.open("w") as stream:
                        midpoint = len(value) // 2
                        stream.write(value[:midpoint])
                        stream.flush()
                        inspect_nonterminal()
                        stream.write(value[midpoint:])
                    return len(value)
                return actual_write(path, value, *args, **kwargs)

            def publish(before, after):
                if Path(after) == directory / "server.json":
                    inspect_nonterminal()
                return actual_replace(before, after)

            client = SimpleNamespace(stdin=io.BytesIO(), wait=lambda: 1)
            with patch.object(opencode, "run_dir", return_value=directory), \
                    patch.object(opencode, "environment", return_value={}), \
                    patch.object(opencode, "start_server", return_value=(SimpleNamespace(pid=123), "http://fixture")), \
                    patch.object(opencode, "stop_group"), patch.object(opencode.subprocess, "Popen", return_value=client), \
                    patch.object(Path, "write_text", direct_write), patch.object(os, "replace", side_effect=publish):
                opencode.serve_run(directory)
            self.assertEqual(observed, ["server publication"])
            self.assertEqual(json.loads((directory / "server.json").read_text()), {"pid": 123, "url": "http://fixture"})
            self.assertEqual(json.loads((directory / "exit.json").read_text()), {"code": 1})
            self.assertTrue(lifecycle.owns(task, "json-run"))

    def test_confirmed_terminal_unit_drains_a_valid_final_event_without_newline(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            error = {"name": "UnknownError", "data": {"message": "final model-server error"}}
            (directory / "events.jsonl").write_text(json.dumps({"type": "step_finish", "part": {
                "reason": "tool-calls"}}) + "\n" + json.dumps({"type": "error", "error": error}))
            (directory / "exit.json").write_text(json.dumps({"code": 1}))
            with patch.object(opencode, "run_dir", return_value=directory), \
                    patch.object(opencode, "active", return_value=False), patch.object(opencode.time, "sleep"):
                facts = opencode.watch("terminal-tail", lambda *event: None)
            self.assertEqual(facts, {"finish": "tool-calls", "code": 1, "error": error})

    def test_live_unit_does_not_consume_unterminated_event_before_terminal_confirmation(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            error = {"name": "UnknownError", "data": {"message": "final error"}}
            (directory / "events.jsonl").write_text(json.dumps({"type": "error", "error": error}))
            (directory / "exit.json").write_text(json.dumps({"code": 1}))
            events = []

            observations = []

            def observe_unit(*args):
                observations.append(None)
                if len(observations) == 2:
                    self.assertEqual(events, [], "a live producer still owns its unterminated line")
                return len(observations) == 1

            with patch.object(opencode, "run_dir", return_value=directory), \
                    patch.object(opencode, "active", side_effect=observe_unit), patch.object(opencode.time, "sleep"):
                facts = opencode.watch("live-tail", lambda *event: events.append(event))
            self.assertEqual(facts["error"], error)

    def test_confirmed_terminal_unit_ignores_a_truncated_final_event(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            (directory / "events.jsonl").write_text('{"type": "error", "error": {"name": "UnknownError"')
            (directory / "exit.json").write_text(json.dumps({"code": 1}))
            with patch.object(opencode, "run_dir", return_value=directory), \
                    patch.object(opencode, "active", return_value=False), patch.object(opencode.time, "sleep"):
                facts = opencode.watch("truncated-tail", lambda *event: None)
            self.assertEqual(facts, {"finish": None, "code": 1})

    @unittest.skipUnless(os.environ.get("COINTOS_NATIVE_PIPELINE_PROBE") == "1", "native observer probe is opt-in")
    def test_native_unit_survives_uncertain_observation_then_reports_real_terminal_error(self):
        support.fresh_ledger(self)
        support.quiet(self)
        agent = "observer-probe-" + secrets.token_hex(4)
        task = support.running(tasks.create("steward", tasks.SYSTEM, "inspect", "Inspect native observer evidence", [6]), agent)
        state.L["agents"][agent]["engaged"] = True
        session = "native-observer-session-" + agent
        unit = opencode.unit(agent)
        actual_run = subprocess.run
        with tempfile.TemporaryDirectory(prefix="cointos-native-observer-") as root:
            directory = Path(root)
            gate = directory / "release"
            os.mkfifo(gate)
            runner = directory / "runner.py"
            runner.write_text(
                "import json, pathlib, sys\n"
                "root=pathlib.Path(sys.argv[1]); session=sys.argv[2]\n"
                "with (root/'events.jsonl').open('w') as events:\n"
                " for malformed in [None, {'sessionID':['bad'],'part':{'type':'text','text':7}}, {'part':{'type':'tool','state':{'input':'bad'}}}]: events.write(json.dumps(malformed)+'\\n')\n"
                " events.write(json.dumps({'type':'text','sessionID':session,'part':{'type':'text','text':'Native observer gate ready'}})+'\\n'); events.flush()\n"
                " with (root/'release').open() as gate: gate.read()\n"
                " events.write(json.dumps({'type':'error','sessionID':session,'error':{'name':'UnknownError','data':{'message':'native fixture model-server error'}}})+'\\n'); events.flush()\n"
                "(root/'exit.json').write_text(json.dumps({'code':1}))\n"
                "sys.exit(1)\n")
            injected = released = False

            def query(command, **kwargs):
                nonlocal injected, released
                self.assertEqual(command, ["systemctl", "--user", "is-active", unit])
                self.assertTrue(lifecycle.owns(task, agent))
                observed = state.L["agents"][agent].get("session") == session
                if observed and not injected:
                    injected = True
                    self.assertEqual(task["session"], session)
                    raise OSError("fixture injected uncertainty for this unit query only")
                result = actual_run(command, **kwargs)
                if injected and not released and result.stdout.strip() in ("active", "activating"):
                    self.assertEqual(state.L["agents"][agent]["session"], session)
                    self.assertEqual(task["session"], session)
                    with gate.open("w") as release:
                        release.write("continue\n")
                    released = True
                return result

            try:
                launched = actual_run(["systemd-run", "--user", "--quiet", "--unit", unit,
                                      "--property=RuntimeMaxSec=30s", sys.executable, str(runner), root, session],
                                     capture_output=True, text=True)
                self.assertEqual(launched.returncode, 0, launched.stderr)
                with patch.object(opencode, "run_dir", return_value=directory), \
                        patch.object(opencode.subprocess, "run", side_effect=query):
                    runs.follow(agent, None, None)
                self.assertTrue(injected)
                self.assertTrue(released)
                self.assertEqual((task["status"], task["session"]), ("waiting", session))
                self.assertNotIn(agent, state.L["agents"])
                self.assertIn("exit code 1", task["note"])
                self.assertIn("native fixture model-server error", task["note"])
            finally:
                actual_run(["systemctl", "--user", "stop", unit], capture_output=True)
                actual_run(["systemctl", "--user", "reset-failed", unit], capture_output=True)

    def test_unit_queries_distinguish_confirmed_terminal_state_from_observation_failure(self):
        for text, code, terminal in (
                ("inactive", 3, True), ("failed", 3, True), ("unknown", 4, True),
                ("inactive", 0, True), ("active", 0, False), ("activating", 0, False),
                ("deactivating", 0, False), ("reloading", 0, False),
                ("", 0, False), ("malformed state", 0, False), ("inactive", 1, False)):
            with self.subTest(text=text, code=code), patch.object(opencode.subprocess, "run", return_value=
                    subprocess.CompletedProcess([], code, text + "\n", "")):
                self.assertEqual(opencode.active("observed-run"), not terminal)
        with patch.object(opencode.subprocess, "run", side_effect=OSError("user bus query unavailable")):
            self.assertTrue(opencode.active("observed-run"))

    def test_transient_systemctl_failure_does_not_end_a_still_live_run(self):
        support.fresh_ledger(self)
        support.quiet(self)
        task = support.running(tasks.create("steward", tasks.SYSTEM, "inspect", "Inspect current work", [6]),
                               "observed-run")
        state.L["agents"]["observed-run"]["engaged"] = True
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            calls = []

            def query(command, **kwargs):
                calls.append(command)
                self.assertTrue(lifecycle.owns(task, "observed-run"))
                self.assertIn("observed-run", state.L["agents"])
                if len(calls) == 2:
                    return subprocess.CompletedProcess(command, 1, "", "Failed to connect to user bus: Interrupted")
                if len(calls) < 4:
                    return subprocess.CompletedProcess(command, 0, "active\n", "")
                if len(calls) == 4:
                    (directory / "events.jsonl").write_text(json.dumps({"type": "error", "error": {
                        "name": "UnknownError", "data": {"message": "the thought failed on the model server"}}}) + "\n")
                    (directory / "exit.json").write_text(json.dumps({"code": 1}))
                return subprocess.CompletedProcess(command, 3, "inactive\n", "")

            with patch.object(opencode, "run_dir", return_value=directory), \
                    patch.object(opencode.subprocess, "run", side_effect=query), patch.object(opencode.time, "sleep"):
                runs.follow("observed-run", None, None)
            self.assertGreaterEqual(len(calls), 4, "ambiguous bus failure cannot authorize unit death")
            self.assertEqual((task["status"], state.L["agents"]), ("waiting", {}))
            self.assertIn("exit code 1", task["note"])
            self.assertIn("the thought failed on the model server", task["note"])


class Completion(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.run_dir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(opencode, "run_dir", return_value=self.run_dir))
        self.enterContext(patch.object(opencode, "active", return_value=False))
        self.project = support.project(self, support.repository(self))
        support.accepted_plan(self.project['path'])
        self.task = support.running(tasks.create("steward", tasks.SYSTEM, "loose-ends", "Look around", [6]), "run-1")
        support.review_frontier(self.task)

    def end(self, *events, code=0, agent="run-1"):
        """The run's unit has exited having written these events; its observer reports it."""
        (self.run_dir / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
        (self.run_dir / "exit.json").write_text(json.dumps({"code": code}))
        runs.follow(agent, None, None)

    # ------------------------------------------------ process exit only reconciles

    def test_exit_after_receipt_releases_the_run_and_keeps_the_settlement(self):
        lifecycle.submit(self.task["id"], "run-1", "complete", "Nothing fell between owners", checked={"scout_result": {"kind": "no_action", "checked_projects": ["p"]}})
        self.assertEqual((self.task["status"], self.task["agent"]), ("done", None))
        # A normal exit precedes the observer's release: not an invariant violation.
        self.assertTrue(all(c["ok"] for c in checks.evaluate(state.CONFIG, state.L, state.now(), {})))
        self.end({"type": "text", "part": {"type": "text", "text": "Done"}},
                 {"type": "step_finish", "part": {"reason": "tool-calls"}})
        self.assertEqual((self.task["status"], self.task["result"]), ("done", "Nothing fell between owners"))
        self.assertEqual((state.L["agents"], state.L["alerts"]), ({}, []))

    def test_receipt_keeps_the_active_conversation_warm_until_release(self):
        state.L["snapshots"]["warm"] = {"owner": self.task["id"]}
        with patch.object(snapshots.cleanup, "queue", wraps=snapshots.cleanup.queue) as retire:
            lifecycle.submit(self.task["id"], "run-1", "complete", "Done", checked={"scout_result": {"kind": "no_action", "checked_projects": ["p"]}})
            self.assertIn("warm", state.L["snapshots"])
            retire.assert_not_called()
            lifecycle.release("run-1", "run ended")
        self.assertNotIn("warm", state.L["snapshots"])
        retire.assert_called_once_with("warm", {"owner": self.task["id"]})
        self.assertTrue(state.L["snapshot_garbage"])

    def test_receipt_delivery_schedules_the_exact_run_for_retirement(self):
        lifecycle.submit(self.task["id"], "run-1", "complete", "Done", checked={"scout_result": {"kind": "no_action", "checked_projects": ["p"]}})
        with patch.object(lifecycle.threading, "Thread") as thread:
            lifecycle.receipt_delivered(self.task["id"], "run-1")
        target = thread.call_args.kwargs["target"]
        with patch.object(lifecycle, "stop") as stop, patch.object(lifecycle, "save"):
            target()
        stop.assert_called_once_with("run-1", "completion receipt delivered", requeue=False, charge=False)

    def test_receipt_delivery_rejects_another_run(self):
        lifecycle.submit(self.task["id"], "run-1", "complete", "Done", checked={"scout_result": {"kind": "no_action", "checked_projects": ["p"]}})
        with self.assertRaisesRegex(ValueError, "no completion receipt"):
            lifecycle.receipt_delivered(self.task["id"], "run-2")

    def test_final_text_and_a_stop_marker_without_a_receipt_are_not_completion(self):
        self.end({"type": "text", "part": {"type": "text", "text": "Complete final summary"}},
                 {"type": "step_finish", "part": {"reason": "stop"}})
        self.assertEqual((self.task["status"], self.task["receipt"]), ("waiting", None))
        self.assertIn("without a completion receipt (finish marker stop, exit code 0)", self.task["note"])

    def test_a_transcript_ending_after_tool_calls_is_decided_by_the_receipt_alone(self):
        lifecycle.submit(self.task["id"], "run-1", "complete", "Queued one command", checked={"scout_result": {"kind": "no_action", "checked_projects": ["p"]}})
        self.end({"type": "step_start", "part": {"type": "step-start"}},
                 {"type": "step_finish", "part": {"reason": "tool-calls"}}, code=1)
        self.assertEqual(self.task["status"], "done")

    def test_an_unexpected_unit_death_requeues_the_task(self):
        runs.follow("run-1", None, None)
        self.assertEqual((self.task["status"], state.L["agents"]), ("waiting", {}))

    def test_runner_errors_are_diagnostics_on_the_retry(self):
        with patch.object(opencode, "watch", side_effect=RuntimeError("serve failed")):
            runs.follow("run-1", None, None)
        self.assertEqual(self.task["status"], "waiting")
        self.assertIn("RuntimeError: serve failed", self.task["note"])

    def test_terminal_model_error_event_is_retained_in_retry_diagnostics(self):
        self.end({"type": "step_finish", "part": {"reason": "tool-calls"}},
                 {"type": "error", "error": {"name": "UnknownError", "data": {
                     "message": '{"message":"the thought failed on the model server; try again"}'}}}, code=1)
        self.assertEqual(self.task["status"], "waiting")
        self.assertIn("exit code 1", self.task["note"])
        self.assertIn("the thought failed on the model server", self.task["note"])

    def test_error_after_receipt_keeps_checked_settlement_authority(self):
        receipt = lifecycle.submit(self.task["id"], "run-1", "complete", "Checked work is complete", checked={"scout_result": {"kind": "no_action", "checked_projects": ["p"]}})
        self.end({"type": "error", "error": {"name": "UnknownError", "data": {
            "message": "the thought failed after its checked receipt"}}}, code=1)
        self.assertEqual(self.task["status"], "done")
        self.assertEqual(self.task["receipt"], receipt)
        self.assertEqual(self.task["result"], "Checked work is complete")
        self.assertEqual(state.L["agents"], {})

    def test_launch_failures_are_uncharged_bounded_and_held(self):
        self.task["runs"] = 1
        state.L["agents"]["run-1"]["engaged"] = False
        self.end(code=1)
        self.assertEqual((self.task["status"], self.task["runs"], self.task["launch_failures"]),
                         ("waiting", 0, 1))
        support.running(self.task, "run-2", worktree=False)
        state.L["agents"]["run-2"]["engaged"] = False
        self.end(code=1, agent="run-2")
        self.assertEqual((self.task["status"], self.task["runs"], self.task["launch_failures"]),
                         ("waiting", 0, 2))
        self.assertEqual(self.task["admission_hold"], "repeated infrastructure launch failure")
        self.assertIn("before reaching the model", state.L["alerts"][-1]["text"])

    def test_first_gateway_admission_clears_launch_failures_in_the_reducer(self):
        self.task["launch_failures"] = 1
        state.L["agents"]["run-1"]["engaged"] = False
        lifecycle.engaged("run-1")
        self.assertTrue(state.L["agents"]["run-1"]["engaged"])
        self.assertEqual(self.task["launch_failures"], 0)

    def test_every_kind_shares_one_bounded_retry_limit(self):
        limit = state.CONFIG["spawner"]["max_runs_per_task"]
        for attempt in range(2, limit + 1):
            runs.follow(f"run-{attempt - 1}", None, None)
            self.assertEqual(self.task["status"], "waiting")
            support.running(self.task, f"run-{attempt}", worktree=False)
        runs.follow(f"run-{limit}", None, None)
        self.assertEqual((self.task["status"], len(state.L["alerts"])), ("failed", 1))

    def test_a_session_learned_by_the_observer_belongs_to_the_current_run_only(self):
        runs.observed("run-1", "session", "session-a")
        self.assertEqual(self.task["session"], "session-a")
        lifecycle.submit(self.task["id"], "run-1", "complete", "Done", checked={"scout_result": {"kind": "no_action", "checked_projects": ["p"]}})
        runs.observed("run-1", "session", "session-b")
        self.assertEqual(self.task["session"], "session-a")

    # ------------------------------------------------ receipts

    def test_a_lost_reply_retry_returns_the_recorded_receipt(self):
        first = lifecycle.submit(self.task["id"], "run-1", "complete", "Clean finding", checked={"scout_result": {"kind": "no_action", "checked_projects": ["p"]}})
        self.assertIs(lifecycle.submit(self.task["id"], "run-1", "complete", "Clean finding"), first)
        with self.assertRaisesRegex(ValueError, "different completion receipt"):
            lifecycle.submit(self.task["id"], "run-1", "blocked", "Clean finding")

    def test_a_stale_run_cannot_submit_or_disturb_a_newer_run(self):
        lifecycle.stop("run-1", "silent too long", requeue=True)
        support.running(self.task, "run-2", worktree=False)
        with self.assertRaisesRegex(ValueError, "only its current run"):
            lifecycle.submit(self.task["id"], "run-1", "complete", "Late summary", checked={"scout_result": {"kind": "no_action", "checked_projects": ["p"]}})
        state.L["agents"]["run-1"] = {**state.L["agents"]["run-2"], "id": "run-1"}  # its late exit report
        lifecycle.ended("run-1", {"finish": "stop", "code": 0})
        self.assertEqual((self.task["status"], self.task["agent"]), ("running", "run-2"))
        self.assertNotIn("run-1", state.L["agents"])

    def test_a_directed_stop_after_the_receipt_does_not_requeue(self):
        lifecycle.submit(self.task["id"], "run-1", "blocked", "the user must choose the boundary")
        lifecycle.stop("run-1", "stopped by the user", requeue=True, charge=False)
        self.assertEqual((self.task["status"], self.task["runs"], self.task["receipt"]["disposition"]), ("done", 1, "blocked"))
        self.assertIn("the user must choose the boundary", state.L["alerts"][-1]["text"])

    def test_a_directed_stop_before_the_receipt_is_uncharged(self):
        lifecycle.stop("run-1", "system halted", requeue=True, charge=False)
        self.assertEqual((self.task["status"], self.task["runs"]), ("waiting", 0))

    def test_killing_a_run_never_decides_its_task_failed(self):
        api.kill_agent({"agent": "run-1"})
        self.assertEqual((self.task["status"], self.task["runs"], self.task["receipt"]), ("waiting", 0, None))
        self.assertNotIn("run-1", state.L["agents"])

    def test_a_receipt_needs_its_kinds_disposition_and_a_summary(self):
        with self.assertRaisesRegex(ValueError, "needs a summary"):
            lifecycle.submit(self.task["id"], "run-1", "complete", " ", checked={"scout_result": {"kind": "no_action", "checked_projects": ["p"]}})
        with self.assertRaisesRegex(ValueError, "complete or blocked"):
            lifecycle.submit(self.task["id"], "run-1", "returned", "No")
        self.assertEqual(self.task["status"], "running")

    # ------------------------------------------------ evidence by kind

    def worker(self, commit=True) -> dict:
        worker = support.running(support.queued(self.project, "parser"), "worker-1")
        (Path(worker["worktree"]) / "parser.c").write_text("int parse(void);\n")
        if commit:
            support.commit(worker["worktree"])
        return worker

    def test_a_worker_receipt_submits_its_committed_branch_for_review(self):
        worker = self.worker()
        receipt = lifecycle.submit(worker["id"], "worker-1", "complete", "Parser exists")
        self.assertEqual(worker["status"], "review")
        self.assertEqual(receipt["evidence"], {"commit": support.git.head(worker["worktree"])})
        lifecycle.release("worker-1", "run ended")
        self.assertTrue(Path(worker["worktree"]).is_dir(), "the integrator still needs the worker's branch")

    def test_a_blocked_worker_goes_directly_to_a_manager(self):
        worker = self.worker()
        lifecycle.submit(worker["id"], "worker-1", "blocked", "Needs decomposition: split")
        self.assertEqual(worker["status"], "failed")
        self.assertTrue(queues.state(queues.records()[worker["record"]])["recoverable"])
        self.assertEqual(spawner.integrations(), [])

    def test_an_uncommitted_worker_cannot_finish(self):
        worker = self.worker(commit=False)
        with self.assertRaisesRegex(ValueError, "commit"):
            lifecycle.submit(worker["id"], "worker-1", "complete", "Done")

    def gardener(self, pending: list[str]) -> dict:
        tree = {"name": "p", "path": self.project["path"], "main_branch": "main", "tree": ".knowledge"}
        self.enterContext(patch.dict(state.CONFIG, trees=[tree]))
        health = {"leaves": [f"yellow\tlocal:{p}\tunverified" for p in pending], "brown": 0, "yellow": len(pending)}
        self.enterContext(patch.object(trees, "health", return_value=health))
        return support.running(tasks.create("garden", tree, "garden", "what/is/selected.md", [3]), "gardener-1")

    def test_a_garden_batch_can_finish_with_other_leaves_still_yellow(self):
        garden = self.gardener(["what/is/other.md"])
        lifecycle.submit(garden["id"], "gardener-1", "complete", "Checked the batch")
        self.assertEqual(garden["status"], "done")

    def test_a_garden_reports_unresolved_selected_leaves_instead_of_looping(self):
        garden = self.gardener(["what/is/selected.md"])
        receipt = lifecycle.submit(garden["id"], "gardener-1", "complete", "Checked the batch")
        self.assertEqual(receipt["evidence"]["unresolved"], ["what/is/selected.md"])
        self.assertIn("what/is/selected.md", state.L["alerts"][-1]["text"])

    def test_a_garden_cannot_finish_without_landing_or_with_uncommitted_corrections(self):
        garden = self.gardener([])
        (Path(garden["worktree"]) / "leaf.md").write_text("corrected\n")
        with self.assertRaisesRegex(ValueError, "commit"):
            lifecycle.submit(garden["id"], "gardener-1", "complete", "Corrected")
        support.commit(garden["worktree"])
        with self.assertRaisesRegex(ValueError, "cointos merge"):
            lifecycle.submit(garden["id"], "gardener-1", "complete", "Corrected")
        support.git.run(self.project["path"], "merge", "--ff-only", garden["branch"])
        lifecycle.submit(garden["id"], "gardener-1", "complete", "Corrected")
        lifecycle.release("gardener-1", "run ended")
        self.assertFalse(Path(garden["worktree"]).exists(), "a landed worktree is removed")

    def test_a_system_operator_needs_only_its_summary(self):
        operator = support.running(tasks.request_operator("look", "Look.", None, None, None, None), "operator-1")
        lifecycle.submit(operator["id"], "operator-1", "complete", "Restarted the viewer")
        self.assertEqual(operator["status"], "done")

    # ------------------------------------------------ integrators

    def integration(self) -> tuple[dict, dict]:
        worker = self.worker()
        lifecycle.submit(worker["id"], "worker-1", "complete", "Done")
        lifecycle.release("worker-1", "run ended")
        integration = tasks.create("integrate", self.project, "integrate-parser", worker["brief"], [2],
                                   item="parser", worker=worker["id"])
        return support.running(integration, "integrator-1"), worker

    def acceptance(self, worker, commit="main"):
        return {"commit": commit, "worker_commit": worker["receipt"]["evidence"]["commit"], "via": "landing"}

    def test_an_integrator_completes_only_through_a_landing(self):
        integration, worker = self.integration()
        with self.assertRaisesRegex(ValueError, "cointos land"):
            lifecycle.submit(integration["id"], "integrator-1", "complete", "Looks good")
        with self.assertRaisesRegex(ValueError, "not the one its receipt submitted"):
            lifecycle.landed(integration, "integrator-1", worker, {**self.acceptance(worker), "worker_commit": "other"})
        lifecycle.landed(integration, "integrator-1", worker, self.acceptance(worker))
        self.assertEqual((worker["status"], integration["status"]), ("done", "done"))
        self.assertEqual(integration["receipt"]["evidence"]["commit"], "main")
        (Path(integration["worktree"]) / "note.md").write_text("an edit that never landed\n")
        unlanded = support.commit(integration["worktree"])
        lifecycle.release("integrator-1", "run ended")
        self.assertFalse(Path(worker["worktree"]).exists(), "an accepted worker's checkout is retired")
        self.assertFalse(Path(integration["worktree"]).exists(), "a settled integration's checkout is retired")
        repo = tasks.place(integration)["path"]
        self.assertEqual(git.head(repo, git.ARCHIVE + integration["branch"]), unlanded,
                         "an unlanded integration commit stays reachable in the archive")

    def test_a_landing_from_another_run_is_refused(self):
        integration, worker = self.integration()
        with self.assertRaisesRegex(ValueError, "only its current run"):
            lifecycle.landed(integration, "integrator-0", worker, self.acceptance(worker))
        self.assertEqual(worker["status"], "review")

    def test_a_return_is_the_integrators_receipt(self):
        integration, worker = self.integration()
        lifecycle.returned(integration, "integrator-1", "Handle empty input")
        lifecycle.returned(integration, "integrator-1", "Handle empty input")  # a lost reply is safe
        self.assertEqual((worker["status"], worker["review"], worker["rejections"], worker["receipt"]),
                         ("waiting", "Handle empty input", 1, None))
        self.assertEqual((integration["status"], integration["receipt"]["disposition"]), ("done", "returned"))

    def test_a_blocked_integrator_fails_its_worker_instead_of_respawning(self):
        integration, worker = self.integration()
        lifecycle.submit(integration["id"], "integrator-1", "blocked", "Main checkout is dirty")
        self.assertEqual((integration["status"], worker["status"]), ("failed", "failed"))

    def test_worker_blocker_dispatches_one_controller_without_an_integrator(self):
        worker = self.worker()
        lifecycle.submit(worker["id"], "worker-1", "blocked", "Contract mismatch: identical inputs share identity")
        lifecycle.release("worker-1", "run ended")
        self.assertEqual(spawner.integrations(), [])
        record = queues.records()[worker["record"]]
        self.assertEqual((queues.status(record), queues.state(record)["recoverable"]), ("blocked", True))
        self.assertEqual(state.L["alerts"], [], "a manager-handleable blocker does not interrupt the user")
        manager = spawner.next_task()
        self.assertEqual((manager["role"], manager["item"]), ("operator", "parser"))
        self.assertIn("Contract mismatch", manager["brief"])
        view = frontier.inspect(manager['id'], state.L)
        self.assertEqual(view['origin_task']['receipt'], worker['receipt'])
        self.assertEqual(view['queue']['brief'], worker['brief'])
        self.assertIn(worker['receipt']['evidence']['commit'], prompts.launch_text(manager, self.project))
        self.assertIs(spawner.next_task(), manager, "reconciliation must not create a second controller")
        support.running(manager, "manager-1")
        lifecycle.submit(manager["id"], "manager-1", "blocked", "the user must choose the public contract")
        self.assertFalse(queues.state(record)["recoverable"])
        self.assertIn("the user must choose", state.L["alerts"][-1]["text"])
        self.assertNotEqual((spawner.next_task() or {}).get("kind"), "decompose")

    def test_exhausted_worker_routes_to_manager_but_exhausted_manager_does_not_loop(self):
        worker = support.queued(self.project, "exhausted", "Build one bounded concern")
        lifecycle.fail(worker, "fresh retries exhausted")
        manager = spawner.next_task()
        self.assertEqual((manager["kind"], manager["item"]), ("operator", "exhausted"))
        lifecycle.fail(manager, "manager retries exhausted")
        self.assertFalse(queues.state(queues.records()[worker["record"]])["recoverable"])
        self.assertNotEqual((spawner.next_task() or {}).get("kind"), "decompose")

    def test_recovery_manager_does_not_inherit_the_failed_workers_limits(self):
        queues.add(self.project, "queued", "tiny", "Build one bounded concern", reasoning_effort="low",
                   budget={"generation_seconds": 1, "generation_tokens": 200})
        worker = tasks.create("item", self.project, "tiny", "Build one bounded concern", [4], item="tiny",
                              record_version=queues.records()["p:tiny"]["version"])
        lifecycle.fail(worker, "fresh retries exhausted")
        with patch.dict(state.CONFIG["reasoning"], manager="medium"):
            manager = spawner.next_task()
        self.assertEqual(manager["kind"], "operator")
        self.assertEqual(manager["budget"], schema.budget(state.CONFIG, role="operator"))
        self.assertEqual(manager["reasoning_effort"], "medium")
        self.assertEqual(worker["budget"], {"generation_seconds": 1, "generation_tokens": 200})

    def test_manager_can_correct_a_brief_without_accepting_the_failed_work(self):
        worker = support.queued(self.project, "wrong", "Impossible contract")
        lifecycle.fail(worker, "contract mismatch")
        manager = support.running(spawner.next_task(), "manager-1")
        as_manager = support.caller(manager, "manager-1")
        api.dispatch("hold", {"item": worker["id"], "caller": as_manager})
        api.dispatch("revise", {"item": worker["id"], "brief": "Corrected contract\nSummary: Fixes the contract so shared identity is allowed.", "reason": "Identity is shared",
                                "caller": as_manager})
        lifecycle.submit(manager["id"], "manager-1", "complete", "Corrected the contract")
        self.assertEqual((worker["status"], queues.status(queues.records()[worker["record"]])), ("waiting", "queued"))
        self.assertNotIn("wrong", queues.landed("p"))
        lifecycle.reconcile()
        self.assertEqual(queues.records()[worker["record"]]["brief"], "Corrected contract\nSummary: Fixes the contract so shared identity is allowed.")

    def test_failed_assignment_dependencies_do_not_prevent_manager_repair(self):
        worker = support.queued(self.project, "wrong-edge", "Depends on: missing\nBuild core")
        lifecycle.fail(worker, "bad prerequisite")
        manager = spawner.next_task()
        self.assertEqual((manager["kind"], manager["item"]), ("operator", "wrong-edge"))

    # ------------------------------------------------ daemon replacement

    def test_a_run_lost_in_a_daemon_replacement_waits_again(self):
        state.L["agents"].clear()
        with patch.object(opencode, "find_processes", return_value={}):
            runs.adopt({})
        self.assertEqual((self.task["status"], self.task["agent"]), ("waiting", None))

    def test_a_run_that_outlived_the_daemon_is_followed_again(self):
        previous = {"agents": dict(state.L["agents"])}
        state.L["agents"].clear()
        with patch.object(runs.keys, "recorded", return_value={"run-1": "key"}), \
                patch.object(opencode, "active", return_value=True), \
                patch.object(opencode, "find_processes", return_value={}), patch.object(runs.threading, "Thread") as thread:
            runs.adopt(previous)
        self.assertEqual((self.task["status"], list(state.L["agents"])), ("running", ["run-1"]))
        thread.assert_called_once_with(target=runs.follow, args=("run-1", None, None), daemon=True)

    def test_a_keyed_run_whose_unit_died_during_shutdown_is_orphaned_uncharged(self):
        previous = {"agents": dict(state.L["agents"])}
        before = self.task["runs"]
        state.L["agents"].clear()
        with patch.object(runs.keys, "recorded", return_value={"run-1": "key"}), \
                patch.object(opencode, "active", return_value=False), \
                patch.object(opencode, "find_processes", return_value={}):
            runs.adopt(previous)
        self.assertEqual((self.task["status"], self.task["agent"], self.task["runs"]),
                         ("waiting", None, before))


if __name__ == "__main__":
    unittest.main()


class Refusals(unittest.TestCase):
    """A refused receipt says what it saw, so the agent fixes it in one step instead of guessing."""

    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.project = support.project(self, support.repository(self))
        self.worker = support.running(support.queued(self.project, "build"), "worker-1")

    def refusal(self, disposition="complete"):
        with self.assertRaises(ValueError) as caught:
            lifecycle.submit(self.worker["id"], "worker-1", disposition, "done")
        return str(caught.exception)

    def test_uncommitted_work_is_listed(self):
        (Path(self.worker["worktree"]) / "scratch.c").write_text("int x;\n")
        self.assertIn("?? scratch.c", self.refusal())
