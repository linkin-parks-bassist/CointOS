import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ecosystem import cli


class IntakeTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.root_patch = patch.object(cli, "ROOT", self.root)
        self.root_patch.start()
        cli.initialize()
        (self.root / "AGENTS.md").write_text("# Test repository instructions\n\nUse explicit evidence.\n", encoding="utf-8")
        (self.root / "config").mkdir(exist_ok=True)
        values = {"version": 1,
                  "authority_profiles": [{"id": "ordinary", "workload_class": "work", "effects": [
                      "read_scoped_files", "write_scoped_files"]}],
                  "workspaces": [{"id": "test", "path": str(self.root.resolve()),
                                  "provenance": "personal", "mode": "active"}]}
        (self.root / "config/workspaces.json").write_text(json.dumps(values), encoding="utf-8")
        canonical = json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
        snapshot = {"schema_version": 1, "values": values,
                    "digest": hashlib.sha256(canonical).hexdigest(),
                    "activated_at": "2026-09-05T00:00:00+00:00",
                    "source_path": str((self.root / "config/workspaces.json").resolve())}
        (self.root / "state/workspaces-policy.json").write_text(
            json.dumps(snapshot), encoding="utf-8")

    def tearDown(self):
        self.root_patch.stop()
        self.temporary.cleanup()

    def task_contract(self, objective):
        root = self.root.resolve()
        return {
            "objective": objective,
            "scope": {"workspace": str(root), "read_paths": [str(root)],
                      "write_paths": [str(root)]},
            "authority_profile": "ordinary",
            "requirements": {"required_capabilities": ["tool-calling"],
                             "minimum_context_tokens": 16384},
            "acceptance": [],
            "budget": {"run_seconds": 300, "task_seconds": 900,
                       "maximum_attempts": 2, "maximum_output_bytes": 65536,
                       "maximum_evidence_items": 20, "maximum_children": 0},
            "source_key": f"test:{objective}", "parent_job_id": None,
            "stop_condition": "Stop after the bounded test task.",
        }

    def test_end_to_end_is_idempotent(self):
        idea = self.root / "inbox/new/rough.md"
        idea.write_text("# Solar Logger\n\nLog the panel output locally.\n", encoding="utf-8")
        cli.run_once()
        jobs = list((self.root / "state/jobs").glob("*.json"))
        self.assertEqual(len(jobs), 1)
        job = json.loads(jobs[0].read_text())
        self.assertEqual(job["state"], "awaiting_review")
        proposal = self.root / job["project"] / "README.md"
        self.assertIn("What observable result", proposal.read_text())
        self.assertTrue((self.root / "inbox/triaged/rough.md").exists())
        cli.run_once()
        self.assertEqual(len(list((self.root / "state/jobs").glob("*.json"))), 1)

    def test_scan_detects_changed_input_before_processing(self):
        idea = self.root / "inbox/new/change.md"
        idea.write_text("first", encoding="utf-8")
        self.assertEqual(cli.scan(), 1)
        idea.write_text("second", encoding="utf-8")
        job_path = next((self.root / "state/jobs").glob("*.json"))
        with self.assertRaises(ValueError):
            cli.process(job_path)
        job = json.loads(job_path.read_text())
        self.assertEqual(job["state"], "failed")

    def test_pause_stops_run(self):
        (self.root / "state/PAUSED").touch()
        with self.assertRaises(SystemExit) as caught:
            cli.run_once()
        self.assertEqual(caught.exception.code, 75)

    def test_role_is_injected_into_prepared_task(self):
        roles = self.root / "roles"
        roles.mkdir()
        (roles / "worker.md").write_text("# Worker\n## Mission\nDo it.\n## Permissions\nRead.\n## Approval required\nWrites.\n## Handoff\nReport.\n")
        job_id = cli.enqueue_task("worker", "Inspect the widget",
                                  task_contract=self.task_contract("Inspect the widget"))
        inventory = {"models": [], "scheduling_policy": {}}
        decision = {"action": "use_loaded", "model": "test-model",
                    "context_tokens": 32768,
                    "reason": "test model-mediated route", "valid": True}
        with patch("ecosystem.models.snapshot", return_value=inventory), \
                patch("ecosystem.models.route", return_value=decision):
            cli.prepare_next()
        prompt = (self.root / f"state/jobs/{job_id}.prompt.md").read_text()
        self.assertIn("# Worker", prompt)
        self.assertIn("Inspect the widget", prompt)
        self.assertIn("# David's workspace instructions", prompt)
        self.assertIn("# Test repository instructions", prompt)

    def test_pending_task_can_be_amended(self):
        roles = self.root / "roles"; roles.mkdir(exist_ok=True)
        (roles / "worker.md").write_text("# Worker\n## Mission\nDo.\n## Permissions\nRead.\n## Approval required\nRoot.\n## Handoff\nReport.\n")
        job_id = cli.enqueue_task("worker", "make an agreement", source="telegram:42",
                                  task_contract=self.task_contract("make an agreement"))
        inventory = {"models": [], "scheduling_policy": {}}
        decision = {"action": "use_loaded", "model": "test-model",
                    "context_tokens": 32768,
                    "reason": "test model-mediated route", "valid": True}
        with patch("ecosystem.models.snapshot", return_value=inventory), \
                patch("ecosystem.models.route", return_value=decision):
            cli.prepare_next()
        self.assertEqual(cli.amend_latest_task(
            "telegram:42", "worker", "have an argument",
            task_contract=self.task_contract("have an argument")), job_id)
        job = json.loads((self.root / f"state/jobs/{job_id}.json").read_text())
        self.assertEqual(job["task"], "have an argument")
        self.assertEqual(job["state"], "queued")

    def test_intake_runner_does_not_consume_agent_tasks(self):
        roles = self.root / "roles"; roles.mkdir(exist_ok=True)
        (roles / "worker.md").write_text("# Worker\n## Mission\nDo.\n## Permissions\nRead.\n## Approval required\nRoot.\n## Handoff\nReport.\n")
        job_id = cli.enqueue_task("worker", "Do a task",
                                  task_contract=self.task_contract("Do a task"))
        cli.run_once()
        job = json.loads((self.root / f"state/jobs/{job_id}.json").read_text())
        self.assertEqual(job["state"], "queued")


if __name__ == "__main__":
    unittest.main()
