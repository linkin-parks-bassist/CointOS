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
        (self.root / "config").mkdir()
        (self.root / "config/executor-opencode.json").write_text("{}")
        job_id = cli.enqueue_task("worker", "Inspect")
        cli.prepare_next()
        def fake_run(command, **kwargs):
            kwargs["stdout"].write(b"done\n")
            return subprocess.CompletedProcess(command, 0)
        self.assertTrue(execute_next(run=fake_run))
        job = json.loads((self.root / f"state/jobs/{job_id}.json").read_text())
        self.assertEqual(job["state"], "completed")
        self.assertEqual(job["exit_code"], 0)
