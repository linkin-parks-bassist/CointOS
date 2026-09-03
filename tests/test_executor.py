import json
import subprocess
from pathlib import Path
from unittest.mock import patch
from test_intake import IntakeTest
from ecosystem import cli
from ecosystem.executor import execute_next


class ExecutorTest(IntakeTest):
    def test_executor_completes_ready_job(self):
        roles = self.root / "roles"; roles.mkdir(exist_ok=True)
        (roles / "worker.md").write_text("# Worker\n## Mission\nDo.\n## Permissions\nRead.\n## Approval required\nRoot.\n## Handoff\nReport.\n")
        (roles / "verifier.md").write_text("# Verifier\n## Mission\nCheck.\n## Permissions\nRead.\n## Approval required\nChanges.\n## Handoff\nVerdict.\n")
        (self.root / "config").mkdir(exist_ok=True)
        (self.root / "config/executor-opencode.json").write_text(
            '{"provider":{"Lemonade":{"models":{"Qwen3.5-4B-GGUF":{},"Qwen3-Coder-30B-A3B-Instruct-GGUF":{}}}}}'
        )
        job_id = cli.enqueue_task("worker", "Inspect")
        cli.prepare_next()
        def fake_run(command, **kwargs):
            kwargs["stdout"].write(b"done\n")
            return subprocess.CompletedProcess(command, 0)
        self.assertTrue(execute_next(run=fake_run))
        job = json.loads((self.root / f"state/jobs/{job_id}.json").read_text())
        self.assertEqual(job["state"], "awaiting_verification")
        self.assertEqual(job["exit_code"], 0)
        verifiers = [json.loads(path.read_text()) for path in (self.root / "state/jobs").glob("*.json")
                     if path.stem != job_id]
        self.assertEqual(len(verifiers), 1)
        self.assertEqual(verifiers[0]["verifies"], job_id)
