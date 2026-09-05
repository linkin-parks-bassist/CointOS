import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch
from tests.test_intake import IntakeTest
from ecosystem import cli
from ecosystem.executor import (
    _job_opencode_config,
    execute_next,
    gated_child_cleanup,
    gated_child_launch,
    gated_child_release,
    gated_child_wait,
    process_identity,
)


class ExecutorTest(IntakeTest):
    def test_gated_child_preserves_identity_config_and_stdin_across_exec(self):
        baseline = set(os.listdir("/proc/self/fd"))
        marker = self.root / "gated-child-marker.json"
        config_fd = os.memfd_create("gated-child-test", os.MFD_CLOEXEC)
        os.write(config_fd, b'{"credential":"only-in-memfd"}')
        os.lseek(config_fd, 0, os.SEEK_SET)
        child_program = """
import json, os, sys
stat = open(f'/proc/{os.getpid()}/stat', encoding='utf-8').read()
start_ticks = int(stat.rsplit(')', 1)[1].split()[19])
config = open(os.environ['OPENCODE_CONFIG'], encoding='utf-8').read()
prompt = sys.stdin.read()
open(sys.argv[1], 'w', encoding='utf-8').write(json.dumps({
    'pid': os.getpid(), 'start_ticks': start_ticks,
    'config': config, 'prompt': prompt,
}))
"""
        environment = os.environ.copy()
        environment["OPENCODE_CONFIG"] = f"/proc/self/fd/{config_fd}"
        record = gated_child_launch(
            config_fd,
            [sys.executable, "-c", child_program, str(marker)],
            environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            self.assertEqual(record["state"], "blocked")
            self.assertEqual(record["pgid"], record["pid"])
            self.assertEqual(process_identity(record["pid"])["start_ticks"],
                             record["start_ticks"])
            time.sleep(0.05)
            self.assertFalse(marker.exists())
            record["process"].stdin.write(b"prompt-remains-stdin")
            record["process"].stdin.close()
            gated_child_release(record)
            outcome = gated_child_wait(record, 2.0)
            self.assertEqual(outcome["returncode"], 0)
            observed = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual(observed["pid"], record["pid"])
            self.assertEqual(observed["start_ticks"], record["start_ticks"])
            self.assertEqual(observed["config"], '{"credential":"only-in-memfd"}')
            self.assertEqual(observed["prompt"], "prompt-remains-stdin")
            self.assertEqual(gated_child_wait(record, 0.1), outcome)
        finally:
            gated_child_cleanup(record, 0.2)
        self.assertEqual(set(os.listdir("/proc/self/fd")), baseline)

    def test_gated_child_post_spawn_failure_reaps_and_balances_fds(self):
        baseline = set(os.listdir("/proc/self/fd"))
        marker = self.root / "must-not-exec"
        config_fd = os.memfd_create("gated-child-failure", os.MFD_CLOEXEC)
        os.write(config_fd, b"config")
        child_program = "import pathlib, sys; pathlib.Path(sys.argv[1]).write_text('ran')"
        environment = os.environ.copy()
        environment["OPENCODE_CONFIG"] = f"/proc/self/fd/{config_fd}"
        record = gated_child_launch(
            config_fd,
            [sys.executable, "-c", child_program, str(marker)],
            environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        started = time.monotonic()
        outcome = gated_child_cleanup(record, 0.2)
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertEqual(outcome["state"], "reaped")
        self.assertIsNotNone(record["process"].returncode)
        self.assertFalse(marker.exists())
        self.assertEqual(gated_child_cleanup(record, 0.2), outcome)
        self.assertEqual(set(os.listdir("/proc/self/fd")), baseline)

    def test_gated_child_injected_post_spawn_failure_reaps_before_raising(self):
        baseline = set(os.listdir("/proc/self/fd"))
        marker = self.root / "injected-failure-must-not-exec"
        config_fd = os.memfd_create("gated-child-injected-failure", os.MFD_CLOEXEC)
        os.write(config_fd, b"config")
        environment = os.environ.copy()
        environment["OPENCODE_CONFIG"] = f"/proc/self/fd/{config_fd}"
        spawned = []

        def capturing_popen(*args, **kwargs):
            process = subprocess.Popen(*args, **kwargs)
            spawned.append(process)
            return process

        identity_calls = 0

        def fail_first_identity(pid):
            nonlocal identity_calls
            identity_calls += 1
            if identity_calls == 1:
                raise RuntimeError("injected after spawn")
            return process_identity(pid)

        child_program = "import pathlib, sys; pathlib.Path(sys.argv[1]).write_text('ran')"
        with patch("ecosystem.executor.process_identity", side_effect=fail_first_identity):
            with self.assertRaisesRegex(RuntimeError, "injected after spawn"):
                gated_child_launch(
                    config_fd,
                    [sys.executable, "-c", child_program, str(marker)],
                    environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    popen=capturing_popen,
                )
        self.assertEqual(len(spawned), 1)
        self.assertIsNotNone(spawned[0].returncode)
        self.assertFalse(marker.exists())
        self.assertEqual(set(os.listdir("/proc/self/fd")), baseline)

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
        job = {
            "id": "task-x",
            "inference_lease": {
                "lease_id": "lease-x",
                "model_id": "model-x",
                "context_tokens": 65536,
                "max_output_tokens": 256,
            },
        }
        opencode = _job_opencode_config(job, b"y" * 32)
        try:
            config = json.loads(os.read(opencode["fd"], 1 << 20))
            options = config["provider"]["Lemonade"]["options"]
            self.assertEqual(options["apiKey"], (b"y" * 32).hex())
            self.assertEqual(opencode["environment"]["OPENCODE_CONFIG"],
                             f"/proc/self/fd/{opencode['fd']}")
            self.assertEqual(opencode["pass_fds"], (opencode["fd"],))
            self.assertFalse((self.root / "state/opencode-configs").exists())
            self.assertFalse((self.root / "state/jobs/task-x.opencode.json").exists())
        finally:
            os.close(opencode["fd"])

    def test_executor_refuses_ready_job_without_authoritative_lease(self):
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
            raise AssertionError("an unleased job must not launch OpenCode")
        with patch("ecosystem.executor.snapshot", return_value=inventory), \
                patch("ecosystem.executor.route", return_value=decision), \
                patch("ecosystem.executor.realize", return_value={
                    "state": "loaded", "model": decision["model"]}):
            self.assertTrue(execute_next(run=fake_run))
        job = json.loads((self.root / f"state/jobs/{job_id}.json").read_text())
        self.assertEqual(job["state"], "failed")
        self.assertIn("inference launch refused", job["error"])
