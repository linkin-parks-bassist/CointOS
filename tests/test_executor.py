import json
import subprocess
from pathlib import Path
from unittest.mock import patch
from tests.test_intake import IntakeTest
from ecosystem import cli
from ecosystem.executor import _job_opencode_config, execute_next


class ExecutorTest(IntakeTest):
    def test_executor_prepares_base_context_without_a_role(self):
        roles = self.root / "roles"
        roles.mkdir(exist_ok=True)
        (roles / "_base.md").write_text(
            "# Base Agent\n\n## Mission\nComplete the assigned task safely.\n",
            encoding="utf-8",
        )
        job_id = cli.enqueue_task(None, "Inspect", agent_name="Noether")
        inventory = {"models": [], "scheduling_policy": {}}
        decision = {"action": "use_loaded", "model": "test-model",
                    "context_tokens": 32768,
                    "reason": "test model-mediated route", "valid": True}
        with patch("ecosystem.models.snapshot", return_value=inventory), \
                patch("ecosystem.models.route", return_value=decision):
            cli.prepare_next()
        prompt = (self.root / f"state/jobs/{job_id}.prompt.md").read_text()
        self.assertIn("# Base Agent", prompt)
        self.assertNotIn("unknown role", prompt.lower())

    def test_per_job_config_is_not_written_into_job_store(self):
        (self.root / "config").mkdir(exist_ok=True)
        (self.root / "config/executor-opencode.json").write_text(
            '{"provider":{"Lemonade":{"models":{"model-x":{}}}}}'
        )
        path = _job_opencode_config({"id": "task-x", "model": "model-x",
                                    "context_tokens": 65536})
        self.assertEqual(path, self.root / "state/opencode-configs/task-x.json")
        self.assertTrue(path.exists())
        self.assertFalse((self.root / "state/jobs/task-x.opencode.json").exists())

    def test_executor_completes_ready_job(self):
        roles = self.root / "roles"; roles.mkdir(exist_ok=True)
        (roles / "worker.md").write_text("# Worker\n## Mission\nDo.\n## Permissions\nRead.\n## Approval required\nRoot.\n## Handoff\nReport.\n")
        (roles / "verifier.md").write_text("# Verifier\n## Mission\nCheck.\n## Permissions\nRead.\n## Approval required\nChanges.\n## Handoff\nVerdict.\n")
        (self.root / "config").mkdir(exist_ok=True)
        (self.root / "config/executor-opencode.json").write_text(
            '{"provider":{"Lemonade":{"models":{"Qwen3.5-4B-GGUF":{},"Qwen3-Coder-30B-A3B-Instruct-GGUF":{}}}}}'
        )
        job_id = cli.enqueue_task("worker", "Inspect")
        inventory = {"models": [{"id": "Qwen3.5-4B-GGUF", "size_gb": 3.34,
                                  "loaded": True}], "scheduling_policy": {
                                      "control_plane": {"model": "Qwen3.5-4B-GGUF"}}}
        decision = {"action": "use_loaded", "model": "Qwen3.5-4B-GGUF",
                    "context_tokens": 32768,
                    "reason": "test model-mediated route", "valid": True}
        with patch("ecosystem.models.snapshot", return_value=inventory), \
                patch("ecosystem.models.route", return_value=decision):
            cli.prepare_next()
        def fake_run(command, **kwargs):
            kwargs["stdout"].write(b"done\n")
            return subprocess.CompletedProcess(command, 0)
        with patch("ecosystem.executor.snapshot", return_value=inventory), \
                patch("ecosystem.executor.route", return_value=decision), \
                patch("ecosystem.verification.enqueue", return_value="verification-test"):
            self.assertTrue(execute_next(run=fake_run))
        job = json.loads((self.root / f"state/jobs/{job_id}.json").read_text())
        self.assertEqual(job["state"], "awaiting_verification")
        self.assertEqual(job["exit_code"], 0)
