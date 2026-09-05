import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch
from tests.test_intake import IntakeTest
from ecosystem import cli
from ecosystem.inference_proxy import (
    completed_run_termination,
    issue_proxy_credential,
    revoke_proxy_credential,
)
from ecosystem.workload_control import observe_workers, release_worker
from ecosystem.executor import (
    execute_next,
    gated_child_cleanup,
    gated_child_launch,
    gated_child_release,
    gated_child_wait,
    close_runner_round,
    launch_runner_round,
    process_identity,
    recover_abandoned_jobs,
)


class ExecutorTest(IntakeTest):
    def test_executor_orders_r1_process_r3_credential_before_gate_release(self):
        events = []
        marker = self.root / "producer-order-marker"
        job_path = self.root / "state/jobs/task-order.json"
        job = {
            "id": "task-order", "kind": "agent-task", "state": "ready",
            "agent_generation": 7, "workload_class": "work",
            "owner_identity": "executor:task-order", "caller_handle": "executor:local",
            "deadline_monotonic": time.monotonic() + 60, "role": "worker",
            "authority_profile": "ordinary", "execution_profile": None,
            "requirements": {"required_capabilities": ["coding"],
                             "minimum_context_tokens": 1024},
            "prompt_tokens": 1, "tool_tokens": 1, "handoff_tokens": 1,
        }
        route = {
            "state": "admitted", "model_id": "model-x",
            "context_tokens_per_sequence": 4096, "max_output_tokens": 128,
            "backend_context_tokens": 4096, "parallel_sequences": 1,
            "parameter_count": 1, "model_bytes": 1, "loaded": True,
        }
        (self.root / "config").mkdir(exist_ok=True)
        (self.root / "config/resource-policy.json").write_text(json.dumps({
            "inference_capacity": {"work_proxy_identity": "proxy:work"},
        }), encoding="utf-8")

        def acquire(_root, request, _clock):
            events.append("acquire")
            return {"state": "starting", "lease_id": "worker-lease", "request": request}

        def launch(*args, **kwargs):
            events.append("spawn")
            return gated_child_launch(*args, **kwargs)

        def register(_root, _lease_id, _pid, _ticks, _clock):
            events.append("register")
            return {"state": "active"}

        def reserve(_root, request, _inventory, _clock):
            events.append("reserve")
            return {"state": "starting", "lease_id": "sequence-lease",
                    "model_id": route["model_id"],
                    "context_tokens": route["context_tokens_per_sequence"],
                    "max_output_tokens": route["max_output_tokens"],
                    "backend_sequence": 1,
                    "expected_release_binding": {"lease_id": "sequence-lease"},
                    "request": request}

        def issue(_root, _lease, sink, _clock):
            events.append("issue")
            sink(b"s" * 32)
            return {"state": "issued"}

        def populate(config, credential):
            events.append("populate")
            from ecosystem.inference_proxy import populate_opencode_credential
            populate_opencode_credential(config, credential)

        def release(record):
            self.assertFalse(marker.exists())
            events.append("release_gate")
            return gated_child_release(record)

        child = [sys.executable, "-c",
                 "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('ran')",
                 str(marker)]
        context = launch_runner_round(
            job, job_path, route, {}, child,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            acquire=acquire, launch=launch, register=register, reserve=reserve,
            issue=issue, populate=populate, release_gate=release,
            release=lambda *_args: None, observe=lambda *_args: None,
        )
        outcome = gated_child_wait(context["launch"], 2.0)
        self.assertEqual(outcome["returncode"], 0)
        self.assertEqual(events, ["acquire", "spawn", "register", "reserve",
                                  "issue", "populate", "release_gate"])
        saved = json.loads(job_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["state"], "running")
        self.assertEqual(saved["runner_generation"], 1)
        self.assertNotIn("inference_lease", saved)
        self.assertNotIn((b"s" * 32).hex(), job_path.read_text(encoding="utf-8"))
        self.assertFalse((self.root / "state/opencode-configs").exists())

    def test_normal_close_releases_r3_before_r1_quiescence(self):
        events = []
        job_path = self.root / "state/jobs/task-close.json"
        job = {"id": "task-close", "state": "running"}
        cli.atomic_json(job_path, job)
        context = {
            "inference_lease": {"lease_id": "sequence-close"},
            "worker_lease": {"lease_id": "worker-close"},
            "launch": {"pid": 101, "start_ticks": 202},
        }

        def termination(_root, _lease_id):
            events.append("termination")
            return {"terminated": True, "evidence_id": "end-one"}

        def revoke(_root, _lease_id, evidence, _clock):
            events.append(("revoke", evidence["evidence_id"]))
            return {"state": "revoked", "sequence": {"state": "released"}}

        def release(_root, _lease_id, outcome, _clock):
            events.append(("release_worker", outcome["state"]))

        def observe(_root, observations, _clock):
            events.append(("observe_worker", observations[0]["inference_lease_active"]))

        result = close_runner_round(
            job, job_path, context, {"state": "reaped", "returncode": 0,
                                     "process_group_alive": False},
            termination=termination, revoke=revoke, release=release, observe=observe,
        )
        self.assertEqual(result["state"], "run_finished")
        self.assertEqual(events, ["termination", ("revoke", "end-one"),
                                  ("release_worker", "run_finished"),
                                  ("observe_worker", False)])
        replay = close_runner_round(
            job, job_path, context, {"state": "reaped", "returncode": 0,
                                     "process_group_alive": False},
            termination=termination, revoke=revoke, release=release, observe=observe,
        )
        self.assertEqual(replay["state"], "run_finished")
        self.assertEqual(len(events), 4)

    def test_ambiguous_close_retains_both_leases_for_reconciliation(self):
        job_path = self.root / "state/jobs/task-ambiguous.json"
        job = {"id": "task-ambiguous", "state": "running"}
        cli.atomic_json(job_path, job)
        context = {
            "inference_lease": {"lease_id": "sequence-ambiguous"},
            "worker_lease": {"lease_id": "worker-ambiguous"},
            "launch": {"pid": 303, "start_ticks": 404},
        }
        result = close_runner_round(
            job, job_path, context, {"returncode": -9},
            termination=lambda *_args: None,
            revoke=lambda *_args: self.fail("ambiguous close must not release R3"),
            release=lambda *_args: self.fail("ambiguous close must not release R1"),
            observe=lambda *_args: self.fail("ambiguous close must not quiesce R1"),
        )
        self.assertEqual(result["state"], "reconciliation_required")
        saved = json.loads(job_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["worker_lease_id"], "worker-ambiguous")
        self.assertEqual(saved["inference_lease_id"], "sequence-ambiguous")

    def test_drain_race_defers_before_spawn_or_credential(self):
        job_path = self.root / "state/jobs/task-drain.json"
        job = {
            "id": "task-drain", "state": "ready", "agent_generation": 4,
            "workload_class": "work", "owner_identity": "executor:drain",
            "caller_handle": "executor:local", "deadline_monotonic": 100.0,
            "role": "worker", "authority_profile": "ordinary",
        }
        route = {"model_id": "model-x", "context_tokens_per_sequence": 4096,
                 "max_output_tokens": 128}
        result = launch_runner_round(
            job, job_path, route, {}, ["must-not-spawn"],
            stdin=None, stdout=None, stderr=None,
            acquire=lambda *_args: {"state": "deferred", "reasons": ["drain"]},
            launch=lambda *_args, **_kwargs: self.fail("drain must prevent spawn"),
            issue=lambda *_args: self.fail("drain must prevent credential"),
        )
        self.assertEqual(result["state"], "deferred")
        saved = json.loads(job_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["state"], "ready")
        self.assertEqual(saved["runner_generation"], 1)
        self.assertEqual(saved["runner_deferred_reasons"], ["drain"])

    def test_execution_claim_initializes_authoritative_identity(self):
        job_path = self.root / "state/jobs/task-claim.json"
        job = {
            "id": "task-claim", "state": "ready",
            "workload_class": "work",
            "remaining_budget": {"run_seconds": 300, "task_seconds": 900,
                                 "maximum_attempts": 2,
                                 "maximum_output_bytes": 65536,
                                 "maximum_evidence_items": 20,
                                 "maximum_children": 1},
            "role": "worker", "authority_profile": "ordinary",
        }
        route = {"model_id": "model-x", "context_tokens_per_sequence": 4096,
                 "max_output_tokens": 128}
        result = launch_runner_round(
            job, job_path, route, {}, ["must-not-spawn"],
            stdin=None, stdout=None, stderr=None,
            acquire=lambda *_args: {"state": "deferred", "reasons": ["drain"]},
            launch=lambda *_args, **_kwargs: self.fail(
                "claim must precede spawn"),
            issue=lambda *_args: self.fail("claim must precede credential"),
            clock=lambda: 100.0,
        )
        self.assertEqual(result["state"], "deferred")
        saved = json.loads(job_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["agent_generation"], 1)
        self.assertEqual(saved["logical_run_state"], "active")
        self.assertEqual(saved["owner_identity"], "executor:task-claim")
        self.assertEqual(saved["caller_handle"], "executor:local")
        self.assertEqual(saved["deadline_monotonic"], 1000.0)
        self.assertEqual(
            saved["runner_worker_request"]["deadline_monotonic"], 1000.0)

    def test_execution_claim_requires_remaining_budget(self):
        job_path = self.root / "state/jobs/task-nobudget.json"
        job = {
            "id": "task-nobudget", "state": "ready",
            "workload_class": "work",
            "role": "worker", "authority_profile": "ordinary",
        }
        route = {"model_id": "model-x", "context_tokens_per_sequence": 4096,
                 "max_output_tokens": 128}
        with self.assertRaisesRegex(ValueError, "remaining task budget"):
            launch_runner_round(
                job, job_path, route, {}, ["must-not-spawn"],
                stdin=None, stdout=None, stderr=None,
                acquire=lambda *_args: self.fail("claim must precede acquire"),
                clock=lambda: 100.0,
            )

    def test_resume_rotates_runner_requests_but_preserves_logical_identity(self):
        (self.root / "config").mkdir(exist_ok=True)
        (self.root / "config/resource-policy.json").write_text(json.dumps({
            "inference_capacity": {"work_proxy_identity": "proxy:work"},
        }), encoding="utf-8")
        job_path = self.root / "state/jobs/task-resume.json"
        job = {
            "id": "task-resume", "state": "ready", "agent_generation": 9,
            "workload_class": "work", "owner_identity": "executor:resume",
            "caller_handle": "executor:local", "deadline_monotonic": 100.0,
            "role": "worker", "authority_profile": "ordinary",
            "execution_profile": None, "opencode_session": "session-one",
            "prompt": "state/jobs/task-resume.prompt.md",
            "output": "logs/runs/task-resume.opencode.log",
        }
        route = {"model_id": "model-x", "context_tokens_per_sequence": 4096,
                 "max_output_tokens": 128}
        worker_requests = []
        sequence_requests = []

        def acquire(_root, request, _clock):
            worker_requests.append(request)
            return {"state": "starting", "lease_id": f"worker-{len(worker_requests)}"}

        def launch(config_fd, *_args, **_kwargs):
            return {"pid": 100 + len(worker_requests), "start_ticks": 200,
                    "pgid": 100 + len(worker_requests),
                    "config_fd": config_fd, "state": "blocked"}

        def reserve(_root, request, _inventory, _clock):
            sequence_requests.append(request)
            return {"state": "starting", "lease_id": f"sequence-{len(sequence_requests)}",
                    "model_id": "model-x", "context_tokens": 4096,
                    "max_output_tokens": 128, "backend_sequence": 1,
                    "expected_release_binding": {
                        "lease_id": f"sequence-{len(sequence_requests)}"}}

        def release_gate(record):
            os.close(record["config_fd"])
            record["config_fd"] = -1

        for _round in range(2):
            launch_runner_round(
                job, job_path, route, {}, ["fake-child"],
                stdin=None, stdout=None, stderr=None,
                acquire=acquire, launch=launch, register=lambda *_args: None,
                reserve=reserve,
                issue=lambda _root, _lease, sink, _clock: sink(b"r" * 32),
                release_gate=release_gate,
            )
            job.update(state="ready")
        self.assertNotEqual(worker_requests[0]["request_id"],
                            worker_requests[1]["request_id"])
        self.assertNotEqual(sequence_requests[0]["request_id"],
                            sequence_requests[1]["request_id"])
        self.assertEqual(job["runner_generation"], 2)
        self.assertEqual(job["agent_generation"], 9)
        self.assertEqual(job["opencode_session"], "session-one")
        self.assertEqual(job["prompt"], "state/jobs/task-resume.prompt.md")
        self.assertEqual(job["output"], "logs/runs/task-resume.opencode.log")

    def test_failure_after_r3_never_releases_either_lease(self):
        events = []
        job_path = self.root / "state/jobs/task-r3-failure.json"
        job = {
            "id": "task-r3-failure", "state": "ready", "agent_generation": 1,
            "workload_class": "work", "owner_identity": "executor:failure",
            "caller_handle": "executor:local", "deadline_monotonic": 100.0,
            "role": "worker", "authority_profile": "ordinary",
        }
        route = {"model_id": "model-x", "context_tokens_per_sequence": 4096,
                 "max_output_tokens": 128}
        (self.root / "config").mkdir(exist_ok=True)
        (self.root / "config/resource-policy.json").write_text(json.dumps({
            "inference_capacity": {"work_proxy_identity": "proxy:work"},
        }), encoding="utf-8")
        record = None

        def launch(config_fd, *_args, **_kwargs):
            nonlocal record
            record = {"pid": 111, "start_ticks": 222, "pgid": 111,
                      "config_fd": config_fd,
                      "gate_write_fd": -1, "state": "blocked", "outcome": {
                          "state": "reaped", "returncode": -15}}
            return record

        def fail_release(launch_record):
            os.close(launch_record["config_fd"])
            launch_record["config_fd"] = -1
            raise RuntimeError("after credential")

        with self.assertRaisesRegex(RuntimeError, "after credential"):
            launch_runner_round(
                job, job_path, route, {}, ["fake-child"],
                stdin=None, stdout=None, stderr=None,
                acquire=lambda _root, request, _clock: {
                    "state": "starting", "lease_id": "worker-failure",
                    "request": request},
                launch=launch, register=lambda *_args: None,
                reserve=lambda _root, request, _inventory, _clock: {
                    "state": "starting", "lease_id": "sequence-failure",
                    "model_id": "model-x", "context_tokens": 4096,
                    "max_output_tokens": 128, "backend_sequence": 1,
                    "expected_release_binding": {"lease_id": "sequence-failure"},
                    "request": request},
                issue=lambda _root, _lease, sink, _clock: sink(b"q" * 32),
                release_gate=fail_release,
                cancel=lambda *_args: events.append("cancel"),
                release=lambda *_args: self.fail("must not release R1"),
                observe=lambda *_args: self.fail("must not observe R1 quiescent"),
            )
        saved = json.loads(job_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["state"], "reconciliation_required")
        self.assertEqual(events, ["cancel"])
        self.assertEqual(saved["worker_lease_id"], "worker-failure")
        self.assertEqual(saved["inference_lease_id"], "sequence-failure")

    def test_waiting_r3_keeps_one_child_gated_until_fresh_revalidation(self):
        (self.root / "config").mkdir(exist_ok=True)
        (self.root / "config/resource-policy.json").write_text(json.dumps({
            "inference_capacity": {"work_proxy_identity": "proxy:work"},
        }), encoding="utf-8")
        job_path = self.root / "state/jobs/task-waiting.json"
        job = {
            "id": "task-waiting", "state": "ready", "agent_generation": 1,
            "workload_class": "work", "owner_identity": "executor:waiting",
            "caller_handle": "executor:local", "deadline_monotonic": 100.0,
            "role": "worker", "authority_profile": "ordinary",
        }
        route = {"model_id": "model-x", "context_tokens_per_sequence": 4096,
                 "max_output_tokens": 128}
        reserve_states = ["waiting_for_preemption", "starting"]
        calls = []

        def launch(config_fd, *_args, **_kwargs):
            calls.append("spawn")
            return {"pid": 121, "start_ticks": 221, "pgid": 121,
                    "config_fd": config_fd, "state": "blocked"}

        def reserve(_root, _request, inventory, _clock):
            state = reserve_states.pop(0)
            calls.append(("reserve", inventory.get("generation"), state))
            result = {"state": state, "lease_id": "sequence-waiting"}
            if state == "starting":
                result.update(model_id="model-x", context_tokens=4096,
                              max_output_tokens=128, backend_sequence=1,
                              expected_release_binding={"lease_id": "sequence-waiting"})
            return result

        def release_gate(record):
            calls.append("release")
            os.close(record["config_fd"])
            record["config_fd"] = -1

        result = launch_runner_round(
            job, job_path, route, {"generation": 1}, ["fake-child"],
            stdin=None, stdout=None, stderr=None,
            acquire=lambda _root, request, _clock: {
                "state": "starting", "lease_id": "worker-waiting", "request": request},
            launch=launch, register=lambda *_args: None, reserve=reserve,
            issue=lambda _root, _lease, sink, _clock: (
                calls.append("issue"), sink(b"w" * 32)),
            release_gate=release_gate,
            refresh_inventory=lambda: {"generation": 2},
            sleeper=lambda _seconds: calls.append("wait"), clock=lambda: 1.0,
        )
        self.assertEqual(result["state"], "running")
        self.assertEqual(calls.count("spawn"), 1)
        self.assertEqual(calls.count("issue"), 1)
        self.assertEqual(calls[-2:], ["issue", "release"])
        self.assertEqual(calls[1:4], [
            ("reserve", 1, "waiting_for_preemption"), "wait",
            ("reserve", 2, "starting"),
        ])

    def test_restart_quarantines_unknown_spawn_intent_without_respawn(self):
        path = self.root / "state/jobs/task-prefix.json"
        cli.atomic_json(path, {
            "id": "task-prefix", "kind": "agent-task",
            "state": "runner_starting", "runner_generation": 3,
            "runner_phase": "spawn_intent", "worker_lease_id": "worker-prefix",
        })
        with patch("ecosystem.executor._stop_recovered_runner", return_value=None):
            self.assertEqual(recover_abandoned_jobs(), 1)
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["state"], "reconciliation_required")
        self.assertEqual(saved["runner_generation"], 3)
        self.assertEqual(saved["worker_lease_id"], "worker-prefix")

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
            with self.assertRaisesRegex(RuntimeError, "injected after spawn") as raised:
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
        failure = raised.exception.launch_failure
        self.assertTrue(failure["spawned"])
        self.assertEqual(failure["pid"], spawned[0].pid)
        self.assertEqual(failure["cleanup"]["state"], "reaped")
        self.assertEqual(failure["cleanup"]["pid"], spawned[0].pid)
        self.assertEqual(set(os.listdir("/proc/self/fd")), baseline)

    def test_gated_child_launch_pre_spawn_failure_reports_never_spawned(self):
        baseline = set(os.listdir("/proc/self/fd"))
        config_fd = os.memfd_create("gated-child-pre-spawn", os.MFD_CLOEXEC)
        environment = os.environ.copy()
        environment["OPENCODE_CONFIG"] = f"/proc/self/fd/{config_fd}"

        def refusing_popen(*_args, **_kwargs):
            raise OSError("popen refused")

        with self.assertRaisesRegex(OSError, "popen refused") as raised:
            gated_child_launch(
                config_fd,
                [sys.executable, "-c", "pass"],
                environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                popen=refusing_popen,
            )
        self.assertEqual(raised.exception.launch_failure, {"spawned": False})
        self.assertEqual(set(os.listdir("/proc/self/fd")), baseline)

    def test_pre_spawn_failure_attests_never_spawned_and_returns_job_to_ready(self):
        from ecosystem import workload_control
        job_path = self.root / "state/jobs/task-never-spawned.json"
        job = {
            "id": "task-never-spawned", "state": "ready", "agent_generation": 1,
            "workload_class": "work", "owner_identity": "executor:never-spawned",
            "caller_handle": "executor:local", "deadline_monotonic": time.monotonic() + 60,
            "role": "worker", "authority_profile": "ordinary",
        }
        route = {"model_id": "model-x", "context_tokens_per_sequence": 4096,
                 "max_output_tokens": 128}
        with patch("ecosystem.executor.opencode_environment",
                   side_effect=OSError("memfd unavailable")):
            with self.assertRaisesRegex(OSError, "memfd unavailable"):
                launch_runner_round(
                    job, job_path, route, {}, ["must-not-spawn"],
                    stdin=None, stdout=None, stderr=None,
                    acquire=lambda _root, request, _clock: (
                        workload_control.acquire_worker(_root, request, _clock)),
                    launch=lambda *_args, **_kwargs: (
                        self.fail("pre-spawn failure must not spawn")),
                    release=workload_control.release_worker,
                    observe=workload_control.observe_workers,
                )
        saved = json.loads(job_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["state"], "ready")
        self.assertEqual(saved["runner_deferred_reasons"], ["OSError: memfd unavailable"])
        self.assertEqual(saved["runner_spawn_failure"]["spawned"], False)
        self.assertEqual(saved["runner_spawn_failure"]["cleanup_state"], None)
        self.assertEqual(saved["runner_spawn_failure"]["phase"], "r1_acquired")
        self.assertIn("memfd unavailable", saved["runner_spawn_failure"]["error"])
        control = json.loads(
            (self.root / "state/workload-control.json").read_text(encoding="utf-8"))
        lease = control["leases"][saved["worker_lease_id"]]
        self.assertEqual(lease["state"], "quiescent")

    def test_post_spawn_failure_attests_reaped_spawn_when_unregistered(self):
        from ecosystem import workload_control
        job_path = self.root / "state/jobs/task-reaped-crash.json"
        job = {
            "id": "task-reaped-crash", "state": "ready", "agent_generation": 1,
            "workload_class": "work", "owner_identity": "executor:reaped-crash",
            "caller_handle": "executor:local", "deadline_monotonic": time.monotonic() + 60,
            "role": "worker", "authority_profile": "ordinary",
        }
        route = {"model_id": "model-x", "context_tokens_per_sequence": 4096,
                 "max_output_tokens": 128}

        def launch_after_spawn_crash(*_args, **_kwargs):
            error = RuntimeError("injected identity failure after spawn")
            error.launch_failure = {
                "spawned": True, "pid": 555, "start_ticks": 666, "pgid": 555,
                "cleanup": {"state": "reaped", "returncode": -15, "pid": 555,
                            "start_ticks": 666, "pgid": 555,
                            "process_group_alive": False},
            }
            raise error

        with self.assertRaisesRegex(RuntimeError, "injected identity failure"):
            launch_runner_round(
                job, job_path, route, {}, ["must-not-spawn"],
                stdin=None, stdout=None, stderr=None,
                acquire=lambda _root, request, _clock: (
                    workload_control.acquire_worker(_root, request, _clock)),
                launch=launch_after_spawn_crash,
                release=workload_control.release_worker,
                observe=workload_control.observe_workers,
            )
        saved = json.loads(job_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["state"], "ready")
        self.assertEqual(saved["runner_spawn_failure"]["spawned"], True)
        self.assertEqual(saved["runner_spawn_failure"]["cleanup_state"], "reaped")
        control = json.loads(
            (self.root / "state/workload-control.json").read_text(encoding="utf-8"))
        lease = control["leases"][saved["worker_lease_id"]]
        self.assertEqual(lease["state"], "quiescent")
        self.assertEqual(lease["observation"]["reaped_spawn"]["pid"], 555)
        self.assertEqual(lease["observation"]["reaped_spawn"]["returncode"], -15)

    def test_post_spawn_failure_retains_lease_when_cleanup_unresolved(self):
        from ecosystem import workload_control
        job_path = self.root / "state/jobs/task-unreaped-crash.json"
        job = {
            "id": "task-unreaped-crash", "state": "ready", "agent_generation": 1,
            "workload_class": "work", "owner_identity": "executor:unreaped-crash",
            "caller_handle": "executor:local", "deadline_monotonic": time.monotonic() + 60,
            "role": "worker", "authority_profile": "ordinary",
        }
        route = {"model_id": "model-x", "context_tokens_per_sequence": 4096,
                 "max_output_tokens": 128}

        def launch_unreaped_crash(*_args, **_kwargs):
            error = RuntimeError("injected unresolved spawn")
            error.launch_failure = {
                "spawned": True, "pid": 666, "start_ticks": None, "pgid": 666,
                "cleanup": {"state": "reconciliation_required", "returncode": None,
                            "pid": 666, "start_ticks": None, "pgid": 666,
                            "process_group_alive": True},
            }
            raise error

        with self.assertRaisesRegex(RuntimeError, "injected unresolved spawn"):
            launch_runner_round(
                job, job_path, route, {}, ["must-not-spawn"],
                stdin=None, stdout=None, stderr=None,
                acquire=lambda _root, request, _clock: (
                    workload_control.acquire_worker(_root, request, _clock)),
                launch=launch_unreaped_crash,
                release=lambda *_args: (
                    self.fail("unresolved spawn crash must not release R1")),
                observe=lambda *_args: (
                    self.fail("unresolved spawn crash must not quiesce R1")),
            )
        saved = json.loads(job_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["state"], "reconciliation_required")
        self.assertEqual(saved["executor_pid"], 666)
        self.assertEqual(saved["runner_spawn_failure"]["spawned"], True)
        self.assertEqual(
            saved["runner_spawn_failure"]["cleanup_state"], "reconciliation_required")
        control = json.loads(
            (self.root / "state/workload-control.json").read_text(encoding="utf-8"))
        lease = control["leases"][saved["worker_lease_id"]]
        self.assertEqual(lease["state"], "starting")

    def test_reaped_leader_does_not_claim_a_live_or_unknown_process_group_ended(self):
        config_fd = os.memfd_create("gated-child-group", os.MFD_CLOEXEC)
        environment = os.environ.copy()
        environment["OPENCODE_CONFIG"] = f"/proc/self/fd/{config_fd}"
        record = gated_child_launch(
            config_fd, [sys.executable, "-c", "pass"], environment,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        gated_child_release(record)
        with patch("ecosystem.executor._process_group_alive", return_value=True):
            unresolved = gated_child_wait(record, 2.0)
        self.assertEqual(unresolved["state"], "reconciliation_required")
        with patch("ecosystem.executor._process_group_alive", return_value=None):
            still_unknown = gated_child_cleanup(record, 0.01)
        self.assertEqual(still_unknown["state"], "reconciliation_required")
        with patch("ecosystem.executor._process_group_alive", return_value=False):
            reaped = gated_child_cleanup(record, 0.01)
        self.assertEqual(reaped["state"], "reaped")

    def test_executor_prepares_base_context_without_a_role(self):
        roles = self.root / "roles"
        roles.mkdir(exist_ok=True)
        (roles / "_base.md").write_text(
            "# Base Agent\n\n## Mission\nComplete the assigned task safely.\n",
            encoding="utf-8",
        )
        job_id = cli.enqueue_task(
            None, "Inspect", agent_name="Noether",
            task_contract=self.task_contract("Inspect"),
        )
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

    def _close_fixture(self):
        root = self.root
        process = {"pid": os.getpid(),
                   "process_start_ticks": int((Path("/proc") / str(os.getpid()) / "stat")
                                              .read_text().rsplit(")", 1)[1].split()[19])}
        binding = {
            "lease_id": "inference-close", "allocation_generation": 1,
            "request_id": "j-close:runner:1:sequence",
            "worker_lease_id": "worker-close", "owner_identity": "worker:close",
            "proxy_identity": "proxy:work", "backend_sequence": 1,
        }
        (root / "config/resource-policy.json").write_text(json.dumps({
            "inference_capacity": {
                "front_sequences": 1, "total_sequences": 4,
                "protected_host_bytes": 1073741824,
                "coin_reserved_bytes": 1073741824,
                "load_transient_bytes": 1073741824,
                "gtt_limit_bytes": 107374182400,
                "maximum_work_models": 2,
                "front_proxy_identity": "proxy:front",
                "work_proxy_identity": "proxy:work",
                "lease_seconds": 3600,
                "release_observer_identity": "observer:inference-backend",
                "release_observation_maximum_age_seconds": 5,
                "clock_domain_id": "host-monotonic:boot-one",
            },
        }), encoding="utf-8")
        values = {
            "version": 1,
            "priority_bands": {"sole_survivor": 1000, "coin": 900,
                               "user_driven": 850,
                               "small_health": 800, "large_health": 700,
                               "default": 600},
            "authority_profiles": {"sole_survivor": "authority:sole",
                                   "coin": "authority:coin"},
            "execution_profiles": {"small_health": "execution:small",
                                   "large_health": "execution:large"},
            "role_priorities": {"default": 100},
            "aging_seconds_per_point": 30.0,
        }
        canonical = json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
        (root / "state/scheduling-policy.json").write_text(json.dumps({
            "schema_version": 1, "values": values,
            "digest": hashlib.sha256(canonical).hexdigest(),
            "activated_at": "2026-09-05T00:00:00+00:00",
            "source_path": str(root / "state/scheduling-policy.json"),
        }), encoding="utf-8")
        (root / "state/workload-control.json").write_text(json.dumps({
            "schema_version": 1, "mode": "open", "generation": 1, "owner": None,
            "leases": {"worker-close": {
                "lease_id": "worker-close", "generation": 1, "state": "active",
                "request": {
                    "workload_class": "work", "model_id": "model-a",
                    "context_tokens": 4096, "max_output_tokens": 128,
                    "deadline_monotonic": 100.0,
                    "owner_identity": "worker:close", "job_id": "j-close",
                    "agent_generation": 1, "caller_handle": "runner",
                    "request_id": "j-close:runner:1:worker",
                    "stop_method": "process_group",
                },
                "acquired_monotonic": 1.0, "process": process,
                "observation": None, "checkpoint_required": False,
            }},
        }), encoding="utf-8")
        sequence_lease = {
            "lease_id": "inference-close", "generation": 1, "state": "starting",
            "class": "work", "workload_class": "work",
            "proxy_identity": "proxy:work", "model_id": "model-a",
            "context_tokens": 4096, "max_output_tokens": 128,
            "backend_sequence": 1, "expires_monotonic": 1000.0,
            "preemption_method": "process_group",
            "release_observer_identity": "observer:inference-backend",
            "allocation_generation": 1, "expected_release_binding": binding,
            "priority": 100, "enqueued_monotonic": 1.0,
            "request": {"request_id": "j-close:runner:1:sequence",
                        "worker_lease_id": "worker-close",
                        "owner_identity": "worker:close"},
            "acquired_monotonic": 1.0, "observed_release": None,
        }
        (root / "state/inference-capacity.json").write_text(json.dumps({
            "version": 1, "generation": 1,
            "leases": {"inference-close": sequence_lease},
        }), encoding="utf-8")
        issue_proxy_credential(root, sequence_lease, lambda _secret: None, lambda: 1.0)
        proxy_path = root / "state/inference-proxy.json"
        proxy = json.loads(proxy_path.read_text(encoding="utf-8"))
        credential = proxy["credentials"]["inference-close"]
        credential["binding"]["process"] = {"pid": 2 ** 30, "process_start_ticks": 1}
        credential["last_backend_termination"] = {
            "terminated": True, "binding": binding,
            "observer_identity": "observer:inference-backend",
            "observer_generation": 1, "observed_monotonic": 11.0,
            "clock_domain_id": "host-monotonic:boot-one", "evidence_id": "end-close",
        }
        proxy_path.write_text(json.dumps(proxy), encoding="utf-8")
        job_path = root / "state/jobs/j-close.json"
        cli.atomic_json(job_path, {
            "id": "j-close", "state": "running", "runner_generation": 1,
            "worker_lease_id": "worker-close",
            "inference_lease_id": "inference-close",
        })
        worker_state = json.loads(
            (root / "state/workload-control.json").read_text(encoding="utf-8"))
        sequence_state = json.loads(
            (root / "state/inference-capacity.json").read_text(encoding="utf-8"))
        return {
            "process": process,
            "job_path": job_path,
            "child_outcome": {"state": "reaped", "returncode": 0,
                              "process_group_alive": False},
            "context": {
                "launch": {"pid": process["pid"],
                           "start_ticks": process["process_start_ticks"],
                           "pgid": process["pid"], "process": object()},
                "worker_lease": worker_state["leases"]["worker-close"],
                "inference_lease": sequence_state["leases"]["inference-close"],
            },
        }

    def _read_owner_state(self, name):
        return (self.root / "state" / name).read_text(encoding="utf-8")

    def test_real_owner_normal_close_reaches_quiescent_and_revoked(self):
        value = self._close_fixture()
        job = json.loads(value["job_path"].read_text(encoding="utf-8"))
        result = close_runner_round(job, value["job_path"], value["context"],
                                    value["child_outcome"], clock=lambda: 12.0)
        self.assertEqual(result["state"], "run_finished")
        worker = json.loads(self._read_owner_state("workload-control.json"))[
            "leases"]["worker-close"]
        self.assertEqual(worker["state"], "quiescent")
        sequence = json.loads(self._read_owner_state("inference-capacity.json"))[
            "leases"]["inference-close"]
        self.assertEqual(sequence["state"], "released")
        self.assertEqual(sequence["observed_release"]["evidence_id"], "end-close")
        credential = json.loads(self._read_owner_state("inference-proxy.json"))[
            "credentials"]["inference-close"]
        self.assertEqual(credential["state"], "revoked")
        self.assertEqual(credential["digest"], "")
        closed = json.loads(value["job_path"].read_text(encoding="utf-8"))
        self.assertEqual(closed["runner_closed_generation"], 1)
        self.assertEqual(closed["runner_close_state"], "run_finished")

    def test_close_replays_revoked_revoke_without_releasing_again(self):
        value = self._close_fixture()
        evidence = completed_run_termination(self.root, "inference-close")
        self.assertIsNotNone(evidence)
        manual = revoke_proxy_credential(self.root, "inference-close", evidence,
                                         lambda: 12.0)
        self.assertEqual(manual["state"], "revoked")
        capacity_after_revoke = self._read_owner_state("inference-capacity.json")
        proxy_after_revoke = self._read_owner_state("inference-proxy.json")
        job = json.loads(value["job_path"].read_text(encoding="utf-8"))
        result = close_runner_round(job, value["job_path"], value["context"],
                                    value["child_outcome"], clock=lambda: 12.0)
        self.assertEqual(result["state"], "run_finished")
        self.assertEqual(self._read_owner_state("inference-capacity.json"),
                         capacity_after_revoke)
        self.assertEqual(self._read_owner_state("inference-proxy.json"),
                         proxy_after_revoke)
        worker = json.loads(self._read_owner_state("workload-control.json"))[
            "leases"]["worker-close"]
        self.assertEqual(worker["state"], "quiescent")

    def test_close_completes_after_releasing_crash_before_sequence_release(self):
        value = self._close_fixture()
        proxy_path = self.root / "state/inference-proxy.json"
        proxy = json.loads(proxy_path.read_text(encoding="utf-8"))
        credential = proxy["credentials"]["inference-close"]
        credential["state"] = "releasing"
        credential["release_requested_monotonic"] = 11.5
        proxy_path.write_text(json.dumps(proxy), encoding="utf-8")
        job = json.loads(value["job_path"].read_text(encoding="utf-8"))
        result = close_runner_round(job, value["job_path"], value["context"],
                                    value["child_outcome"], clock=lambda: 12.0)
        self.assertEqual(result["state"], "run_finished")
        sequence = json.loads(self._read_owner_state("inference-capacity.json"))[
            "leases"]["inference-close"]
        self.assertEqual(sequence["state"], "released")
        credential = json.loads(proxy_path.read_text(encoding="utf-8"))[
            "credentials"]["inference-close"]
        self.assertEqual(credential["state"], "revoked")
        worker = json.loads(self._read_owner_state("workload-control.json"))[
            "leases"]["worker-close"]
        self.assertEqual(worker["state"], "quiescent")

    def test_close_replay_after_marker_leaves_all_owner_state_unchanged(self):
        value = self._close_fixture()
        job = json.loads(value["job_path"].read_text(encoding="utf-8"))
        first = close_runner_round(job, value["job_path"], value["context"],
                                   value["child_outcome"], clock=lambda: 12.0)
        self.assertEqual(first["state"], "run_finished")
        snapshots = {
            "workload-control.json": self._read_owner_state("workload-control.json"),
            "inference-capacity.json": self._read_owner_state("inference-capacity.json"),
            "inference-proxy.json": self._read_owner_state("inference-proxy.json"),
            "jobs/j-close.json": value["job_path"].read_text(encoding="utf-8"),
        }
        replay = close_runner_round(job, value["job_path"], value["context"],
                                    value["child_outcome"], clock=lambda: 12.0)
        self.assertEqual(replay, {"state": "run_finished"})
        self.assertEqual(self._read_owner_state("workload-control.json"),
                         snapshots["workload-control.json"])
        self.assertEqual(self._read_owner_state("inference-capacity.json"),
                         snapshots["inference-capacity.json"])
        self.assertEqual(self._read_owner_state("inference-proxy.json"),
                         snapshots["inference-proxy.json"])
        self.assertEqual(value["job_path"].read_text(encoding="utf-8"),
                         snapshots["jobs/j-close.json"])

    def test_close_completes_after_r1_release_committed_without_job_marker(self):
        value = self._close_fixture()
        process = value["process"]
        evidence = completed_run_termination(self.root, "inference-close")
        self.assertIsNotNone(evidence)
        revoke_proxy_credential(self.root, "inference-close", evidence, lambda: 11.5)
        release_worker(self.root, "worker-close",
                       {"state": "run_finished", "returncode": 0}, lambda: 11.6)
        observe_workers(self.root, [{
            "lease_id": "worker-close", "pid": process["pid"],
            "process_start_ticks": process["process_start_ticks"],
            "process_group_alive": False, "backend_request_active": False,
            "inference_lease_active": False,
        }], lambda: 11.7)
        job = json.loads(value["job_path"].read_text(encoding="utf-8"))
        result = close_runner_round(job, value["job_path"], value["context"],
                                    value["child_outcome"], clock=lambda: 12.0)
        self.assertEqual(result["state"], "run_finished")
        worker = json.loads(self._read_owner_state("workload-control.json"))[
            "leases"]["worker-close"]
        self.assertEqual(worker["state"], "quiescent")
        closed = json.loads(value["job_path"].read_text(encoding="utf-8"))
        self.assertEqual(closed["runner_closed_generation"], 1)
        self.assertEqual(closed["runner_close_state"], "run_finished")
