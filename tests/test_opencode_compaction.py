"""Same-session recovery must establish a native compaction boundary before adding a turn."""
import json
import os
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from cointos import opencode


def marker():
    return {"info": {"id": "msg_marker", "role": "user"}, "parts": [{"type": "compaction"}]}


def summary(**changes):
    return {"info": {"id": "msg_summary", "role": "assistant", "parentID": "msg_marker",
                     "summary": True, "finish": "stop", **changes}, "parts": [{"type": "text", "text": "Summary"}]}


class CompactionRecovery(unittest.TestCase):
    def test_only_a_successful_summary_of_the_latest_marker_closes_the_boundary(self):
        cases = [([], False), ([marker()], True), ([marker(), summary(finish=None)], True),
                 ([marker(), summary(error={"name": "Interrupted"})], True),
                 ([marker(), summary(parentID="msg_continue")], True), ([marker(), summary()], False),
                 ([marker(), summary(finish=None),
                   {"info": {"id": "msg_real", "role": "user"}, "parts": [{"type": "text"}]}], False)]
        for messages, pending in cases:
            with self.subTest(messages=messages), mock.patch.object(opencode, "session_request", return_value=messages):
                self.assertEqual(opencode.compaction_pending("url", "session", "worktree"), pending)

    def test_native_summary_finishes_before_recovery_can_add_its_turn(self):
        with mock.patch.object(opencode, "session_request", side_effect=[[marker()], True, [marker(), summary()]]) as request:
            self.assertTrue(opencode.finish_compaction("url", "session", "worktree", {"providerID": "p", "modelID": "m"}))
        self.assertEqual([c.args[3] for c in request.call_args_list], ["message", "summarize", "message"])
        self.assertEqual(request.call_args_list[1].args[4], {"providerID": "p", "modelID": "m", "auto": False})

    def test_completed_compaction_does_not_spend_another_summary(self):
        with mock.patch.object(opencode, "session_request", return_value=[marker(), summary()]) as request:
            self.assertFalse(opencode.finish_compaction("url", "session", "worktree", {}))
        request.assert_called_once()

    def test_failed_native_summary_withholds_recovery_even_if_endpoint_returned_true(self):
        with mock.patch.object(opencode, "session_request", side_effect=[[marker()], True, [marker(), summary(error="failed")]]):
            with self.assertRaisesRegex(RuntimeError, "recovery turn withheld"):
                opencode.finish_compaction("url", "session", "worktree", {})

    def test_repair_failure_stops_server_and_never_starts_a_client(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "run.json").write_text(json.dumps({"task": {"id": "p:t", "worktree": temp},
                "session": "session", "model": {}, "command": ["opencode", "run"], "text": "Continue."}))
            with mock.patch.object(opencode, "start_server", return_value=(mock.Mock(pid=123), "url")), \
                 mock.patch.object(opencode, "finish_compaction", side_effect=RuntimeError("summary failed")), \
                 mock.patch.object(opencode.subprocess, "Popen") as client, mock.patch.object(opencode, "stop_group") as stop:
                with self.assertRaisesRegex(RuntimeError, "summary failed"):
                    opencode.serve_run(directory)
                client.assert_not_called()
                stop.assert_called_once_with(123)
            self.assertEqual(json.loads((directory / "exit.json").read_text()), {"code": 1})


class ScopedCompactionLaunch(unittest.TestCase):
    def test_checked_executable_and_header_mode_are_captured_together(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / 'bin').mkdir()
            candidate = root / 'bin/opencode-compaction'; candidate.write_bytes(b'checked fixture CLI')
            directory = root / 'run'
            config = {'work_model': 'model', 'memory': {'agent_limit_gb': 1}, 'structured_compaction': True}
            task = {'id': 'p:t', 'role': 'worker', 'title': 'fixture', 'worktree': temp}
            with mock.patch.object(opencode, 'ROOT', root), \
                 mock.patch.object(opencode, 'COMPACTION_CLI_SHA', hashlib.sha256(candidate.read_bytes()).hexdigest()), \
                 mock.patch.object(opencode, 'run_dir', return_value=directory), \
                 mock.patch.object(opencode, 'settings', return_value={}), \
                 mock.patch.object(opencode.subprocess, 'run'):
                opencode.launch(config, 'fixture', task, 'fixture-key', 'Continue.', [])
            spec = json.loads((directory / 'run.json').read_text())
            env = opencode.environment(directory, spec)
            self.assertEqual(spec['command'][0], str(candidate))
            self.assertEqual(env['COINTOS_OPENCODE_BINARY'], spec['command'][0])
            self.assertEqual(env['COINTOS_STRUCTURED_COMPACTION'], '1')
            self.assertNotEqual(spec['command'][0], opencode.OPENCODE)

    def test_default_launch_cannot_inherit_an_enabled_prototype_header(self):
        with mock.patch.dict(os.environ, {'COINTOS_STRUCTURED_COMPACTION': '1'}):
            env = opencode.environment(Path('/tmp/fixture'), {'task': {'id': 't'}, 'command': [opencode.OPENCODE, 'run']})
        self.assertEqual(env['COINTOS_STRUCTURED_COMPACTION'], '0')
        self.assertEqual(env['COINTOS_OPENCODE_BINARY'], opencode.OPENCODE)

    def test_unknown_candidate_or_nonboolean_option_fails_before_unit_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'bin').mkdir();(root/'bin/opencode-compaction').write_bytes(b'unknown CLI')
            with mock.patch.object(opencode,'ROOT',root), mock.patch.object(opencode.subprocess,'run') as run:
                for option in (True, 'false'):
                    with self.assertRaises(ValueError):
                        opencode.launch({'structured_compaction': option}, 'fixture', {}, '', '', [])
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
