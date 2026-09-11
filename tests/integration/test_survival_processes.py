"""Offline process tests for the permanent Cointelprofessional survival plane."""

import hashlib
import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from survival import guardian, system_control, systemd_notify, telegram_api


base = Path(__file__).resolve().parent.parent.parent
unit_directory = base / "services" / "system"
installer_path = base / "scripts" / "install-survival-plane"
installer_source_paths = (
    "scripts/install-survival-plane",
    "scripts/cointelprofessional-checkpoint",
    "scripts/cointelprofessional-gateway",
    "scripts/cointelprofessional-guardian",
    "survival/__init__.py",
    "survival/checkpoint.py",
    "survival/gateway.py",
    "survival/guardian.py",
    "survival/json_codec.py",
    "survival/lifecycle.py",
    "survival/protocol.py",
    "survival/records.py",
    "survival/system_control.py",
    "survival/systemd_notify.py",
    "survival/telegram_api.py",
    "survival/time_policy.py",
    "config/time.cfg",
    "config/survival-lifecycle.json",
    "services/system/cointelprofessional-survival.slice",
    "services/system/cointelprofessional-checkpoint.service",
    "services/system/cointelprofessional-gateway.service",
    "services/system/cointelprofessional-guardian.socket",
    "services/system/cointelprofessional-guardian.service",
)


def load_unit(name):
    return (unit_directory / name).read_text(encoding="utf-8")


def destructible_units_from(text):
    found = []
    for line in text.splitlines():
        fields = line.split("=", 1)
        if len(fields) != 2:
            continue
        key, value = fields
        if key.strip().lower() not in {
            "wants", "requires", "after", "before", "partof", "bindsto",
            "onfailure",
        }:
            continue
        found.extend(
            token for token in value.split()
            if token.endswith(".service") and token not in found
        )
    return found


def start_python_harness(root, name, source, environment=None):
    path = root / name
    path.write_text(source, encoding="utf-8")
    process_environment = os.environ.copy()
    process_environment["PYTHONPATH"] = (
        str(base) + ":" + process_environment.get("PYTHONPATH", "")
    )
    if environment is not None:
        process_environment.update(environment)
    return subprocess.Popen(
        [sys.executable, str(path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=process_environment,
        start_new_session=True,
    )


def stop_process(process):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        _stdout, stderr = process.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        _stdout, stderr = process.communicate(timeout=3)
    return stderr.decode("utf-8", errors="replace")


def wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise TimeoutError("condition did not become true")


def receive_notification(receiver, timeout):
    receiver.settimeout(timeout)
    payload, ancillary, _flags, _address = receiver.recvmsg(
        4096, socket.CMSG_SPACE(struct.calcsize("@3i")),
    )
    sender_pid = None
    for level, kind, data in ancillary:
        if level == socket.SOL_SOCKET and kind == socket.SCM_CREDENTIALS:
            sender_pid, _uid, _gid = struct.unpack("@3i", data[:struct.calcsize("@3i")])
    return payload.decode("utf-8"), sender_pid


def wait_for_notifications(receiver, required, timeout=4.0):
    messages = []
    observed = set()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            messages.append(receive_notification(receiver, deadline - time.monotonic()))
        except socket.timeout:
            break
        observed = {message for message, _pid in messages}
        if required <= observed:
            return messages
    raise AssertionError(f"missing notifications: {sorted(required - observed)}")


def drain_notifications(receiver):
    receiver.setblocking(False)
    try:
        while True:
            receiver.recv(4096)
    except BlockingIOError:
        pass
    finally:
        receiver.setblocking(True)


def read_pid_log(path):
    if not path.exists():
        return []
    return [int(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_survival_units_are_not_stoppable_by_guardian():
    text = load_unit("cointelprofessional-guardian.service")
    assert "cointelprofessional-gateway.service" not in destructible_units_from(text)
    assert "cointelprofessional-checkpoint.service" in system_control.SURVIVAL_UNITS


def test_checkpoint_unit_is_unprivileged_activation_independent_infrastructure():
    text = load_unit("cointelprofessional-checkpoint.service")
    for setting in (
        "User=david",
        "Restart=always",
        "StartLimitIntervalSec=0",
        "Slice=cointelprofessional-survival.slice",
        "ExecStart=/usr/bin/python3 -m survival.checkpoint",
        "WorkingDirectory=/usr/local/lib/cointelprofessional-survival/current",
        "Environment=SURVIVAL_STORE_DIR=/var/lib/cointelprofessional",
        "Environment=AGENT_STATE_DIR=/home/david/agent-ecosystem/state",
        "Environment=TIME_CONFIG_PATH=/etc/cointelprofessional/time.cfg",
        "Environment=LIFECYCLE_CATALOG_PATH=/usr/local/lib/cointelprofessional-survival/current/config/survival-lifecycle.json",
        "ReadOnlyPaths=/var/lib/cointelprofessional/checkpoint-requests",
        "BindReadOnlyPaths=-/home/david/agent-ecosystem/state/jobs -/home/david/agent-ecosystem/logs/runs",
        "ReadWritePaths=/var/lib/cointelprofessional/checkpoint-results",
        "InaccessiblePaths=-/run/cointelprofessional/guardian.sock",
        "NoNewPrivileges=true",
        "ProtectSystem=strict",
        "ProtectHome=tmpfs",
        "WantedBy=multi-user.target",
    ):
        assert setting in text
    assert "User=root" not in text
    assert "SupplementaryGroups=cointelprofessional_command" not in text
    assert "GUARDIAN_SOCKET_PATH" not in text


def test_gateway_unit_has_exact_supervision_contract():
    text = load_unit("cointelprofessional-gateway.service")
    for setting in (
        "Type=notify", "NotifyAccess=main", "User=cointelprofessional",
        "Restart=always", "RestartSec=250ms", "StartLimitIntervalSec=0",
        "WatchdogSec=10s", "Slice=cointelprofessional-survival.slice",
        "LoadCredential=telegram_bot_token:/etc/cointelprofessional/telegram_bot_token",
    ):
        assert setting in text


def test_guardian_unit_has_exact_supervision_and_activation_contract():
    text = load_unit("cointelprofessional-guardian.service")
    for setting in (
        "Type=notify", "NotifyAccess=main", "User=root",
        "Group=cointelprofessional_command", "Restart=always",
        "WatchdogSec=10s", "Sockets=cointelprofessional-guardian.socket",
        "RuntimeDirectory=cointelprofessional", "RuntimeDirectoryMode=0750",
        "RuntimeDirectoryPreserve=yes",
        "WantedBy=multi-user.target",
    ):
        assert setting in text


def test_guardian_socket_uses_the_private_command_group():
    text = load_unit("cointelprofessional-guardian.socket")
    assert "ListenStream=/run/cointelprofessional/guardian.sock" in text
    assert "SocketUser=root" in text
    assert "SocketGroup=cointelprofessional_command" in text
    assert "SocketMode=0660" in text
    assert "Accept=no" in text


def test_units_execute_only_the_installed_snapshot():
    modules = {
        "cointelprofessional-checkpoint.service": "survival.checkpoint",
        "cointelprofessional-gateway.service": "survival.gateway",
        "cointelprofessional-guardian.service": "survival.guardian",
    }
    for name, module in modules.items():
        text = load_unit(name)
        assert f"ExecStart=/usr/bin/python3 -m {module}" in text
        assert "WorkingDirectory=/usr/local/lib/cointelprofessional-survival/current" in text
        assert "%h" not in text
        assert f"ExecStart=/home/" not in text


def test_units_use_systemd_notification_without_remote_documentation():
    for path in unit_directory.glob("cointelprofessional-*"):
        text = path.read_text(encoding="utf-8")
        assert "Environment=NOTIFY_SOCKET=" not in text
        assert "github.com" not in text


def test_units_project_task_3_and_4_paths_and_groups():
    gateway_text = load_unit("cointelprofessional-gateway.service")
    assert "SupplementaryGroups=cointelprofessional_command" in gateway_text
    assert "SupplementaryGroups=cointelprofessional_command agent_ecosystem_io" not in gateway_text
    assert "Environment=GUARDIAN_SOCKET_PATH=/run/cointelprofessional/guardian.sock" in gateway_text
    assert "Environment=SURVIVAL_STORE_DIR=/var/lib/cointelprofessional" in gateway_text
    assert "Environment=TIME_CONFIG_PATH=/etc/cointelprofessional/time.cfg" in gateway_text
    assert "/var/lib/cointelprofessional/gateway/critical-attempts" in gateway_text
    assert "Environment=CREDENTIALS_DIRECTORY=" not in gateway_text
    guardian_text = load_unit("cointelprofessional-guardian.service")
    assert "EnvironmentFile=/etc/cointelprofessional/guardian.env" in guardian_text
    assert "Environment=GUARDIAN_SOCKET_PATH=/run/cointelprofessional/guardian.sock" in guardian_text
    assert "Environment=SURVIVAL_STORE_DIR=/var/lib/cointelprofessional" in guardian_text
    assert "Environment=TIME_CONFIG_PATH=/etc/cointelprofessional/time.cfg" in guardian_text
    assert "Environment=LIFECYCLE_CATALOG_PATH=/usr/local/lib/cointelprofessional-survival/current/config/survival-lifecycle.json" in guardian_text
    assert "Environment=AGENT_STATE_DIR=/home/david/agent-ecosystem/state" in guardian_text
    assert "Environment=INCIDENT_DESTINATION_PATH=/etc/cointelprofessional/incident_destination.json" in guardian_text
    assert "/etc/cointelprofessional/incident_destination.json" in guardian_text
    assert "/var/lib/cointelprofessional/lifecycle-progress" in guardian_text
    assert "ProtectHome=read-only" in guardian_text
    assert "/etc/cointelprofessional/incident_destination.json" not in gateway_text
    assert "/var/lib/cointelprofessional/lifecycle-progress" not in gateway_text
    assert "/var/lib/cointelprofessional/gateway/critical-attempts" not in guardian_text
    assert "/var/lib/cointelprofessional/gateway/delivery-health-incidents" in gateway_text
    assert "/var/lib/cointelprofessional/gateway/delivery-health-incidents" not in guardian_text


def test_lifecycle_progress_is_deduplicated_across_guardian_process_restart():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        store = root / "store"
        agent_state = root / "agent-state"
        agent_state.mkdir()
        path = system_control.accept_request(
            store,
            {
                "schema_version": 1,
                "request_id": "telegram-700",
                "telegram_update_id": 700,
                "telegram_user_id": 99,
                "command": "reset",
                "received_at": "2026-09-05T00:00:00+00:00",
            },
            previous_pause=False,
        )
        source = f'''\
from pathlib import Path
from survival import guardian, system_control, time_policy

store = Path({str(store)!r})
config = {{
    "store_path": store,
    "agent_state_path": Path({str(agent_state)!r}),
    "timing_policy": time_policy.load(Path({str(base / "config/time.cfg")!r})),
    "incident_destination": {{
        "schema_version": 1,
        "telegram_user_id": 42,
        "chat_id": 42,
    }},
}}

def direct(kind):
    def run(_effect, _policy):
        if kind == "close_admission":
            return {{"ok": False, "error": "stable injected blocker"}}
        return {{"ok": True}}
    return run

adapters = {{"system": lambda *_: {{"ok": True}}, "user": lambda *_: {{"ok": True}}}}
for kind in (
    "notify", "close_admission", "checkpoint", "reconcile", "verify",
    "resume", "finish",
):
    adapters[kind] = direct(kind)
guardian.resume_pending_request(config, adapters)
'''
        process_environment = os.environ.copy()
        process_environment["PYTHONPATH"] = (
            str(base) + ":" + process_environment.get("PYTHONPATH", "")
        )

        first = subprocess.run(
            [sys.executable, "-c", source], capture_output=True, text=True,
            env=process_environment, timeout=5, check=False,
        )
        assert first.returncode == 0, first.stderr
        first_reports = sorted((store / "outbox/critical").glob(
            "lifecycle-progress-*.json",
        ))
        assert len(first_reports) == 2

        second = subprocess.run(
            [sys.executable, "-c", source], capture_output=True, text=True,
            env=process_environment, timeout=5, check=False,
        )
        assert second.returncode == 0, second.stderr
        assert sorted((store / "outbox/critical").glob(
            "lifecycle-progress-*.json",
        )) == first_reports
        assert system_control._read_request(path)["state"]["phase"] == "blocked"


def test_delivery_ambiguity_is_terminal_across_gateway_process_restart():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        store = root / "store"
        source_path = store / "outbox/critical/process-message.json"
        source_path.parent.mkdir(parents=True)
        source_path.write_text(json.dumps({
            "schema_version": 1,
            "id": "process-message",
            "chat_id": 42,
            "text": "process restart delivery",
            "egress_state": "ready",
        }), encoding="utf-8")
        first_source = f'''\
from pathlib import Path
from survival import gateway
assert gateway.drain_critical_outbox(
    Path({str(store)!r}), lambda *_arguments: True,
) == 1
'''
        process_environment = os.environ.copy()
        process_environment["PYTHONPATH"] = (
            str(base) + ":" + process_environment.get("PYTHONPATH", "")
        )
        first = subprocess.run(
            [sys.executable, "-c", first_source], capture_output=True, text=True,
            env=process_environment, timeout=5, check=False,
        )
        assert first.returncode == 0, first.stderr
        delivery_path = store / "gateway/critical-delivery/process-message.json"
        delivery_path.unlink()
        replay_marker = root / "replayed"
        second_source = f'''\
from pathlib import Path
from survival import gateway

def forbidden_send(*_arguments):
    Path({str(replay_marker)!r}).write_text("replayed", encoding="utf-8")
    return True

assert gateway.drain_critical_outbox(
    Path({str(store)!r}), forbidden_send,
) == 0
'''
        second = subprocess.run(
            [sys.executable, "-c", second_source], capture_output=True, text=True,
            env=process_environment, timeout=5, check=False,
        )
        assert second.returncode == 0, second.stderr
        assert not replay_marker.exists()
        assert json.loads(delivery_path.read_text())["egress_state"] == "delivery_unknown"


def test_checkpoint_process_consumes_a_real_mixed_request_without_privileged_state():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        store = root / "store"
        agent_state = root / "agent-state"
        jobs = agent_state / "jobs"
        logs = root / "logs/runs"
        request_root = store / "checkpoint-requests"
        request_root.mkdir(parents=True)
        jobs.mkdir(parents=True)
        logs.mkdir(parents=True)
        deadline = time.monotonic() + 30.0
        (request_root / "telegram-1.json").write_text(json.dumps({
            "schema_version": 1,
            "request_id": "telegram-1",
            "job_ids": ["task-active", "task-finished", "task-unsupported"],
            "requested_at": "2026-09-05T00:00:00+00:00",
            "boot_id": telegram_api.current_boot_id(),
            "deadline_monotonic": deadline,
        }), encoding="utf-8")
        (jobs / "task-active.json").write_text(json.dumps({
            "id": "task-active",
            "kind": "agent-task",
            "state": "running",
            "opencode_session": "ses_process",
            "output": "logs/runs/task-active.opencode.log",
        }), encoding="utf-8")
        (logs / "task-active.opencode.log").write_text(
            '{"sessionID":"ses_process"}\n', encoding="utf-8",
        )
        (jobs / "task-finished.json").write_text(json.dumps({
            "id": "task-finished", "kind": "agent-task", "state": "completed",
        }), encoding="utf-8")
        (jobs / "task-unsupported.json").write_text(json.dumps({
            "id": "task-unsupported", "kind": "agent-task", "state": "running",
        }), encoding="utf-8")
        guardian_sentinel = root / "guardian.sock"
        guardian_sentinel.write_text("not a consumer input", encoding="utf-8")
        environment = os.environ.copy()
        environment.update({
            "PYTHONPATH": str(base),
            "SURVIVAL_STORE_DIR": str(store),
            "AGENT_STATE_DIR": str(agent_state),
            "TIME_CONFIG_PATH": str(base / "config/time.cfg"),
            "LIFECYCLE_CATALOG_PATH": str(base / "config/survival-lifecycle.json"),
            "GUARDIAN_SOCKET_PATH": str(guardian_sentinel),
        })
        process = subprocess.Popen(
            [str(base / "scripts/cointelprofessional-checkpoint")],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=environment,
            start_new_session=True,
        )
        result_directory = store / "checkpoint-results/telegram-1"
        try:
            wait_until(lambda: len(list(result_directory.glob("*.json"))) == 3)
            assert process.poll() is None
        finally:
            stderr = stop_process(process)
        results = {
            path.stem: json.loads(path.read_text(encoding="utf-8"))
            for path in result_directory.glob("*.json")
        }
        assert {job_id: result["state"] for job_id, result in results.items()} == {
            "task-active": "checkpointed",
            "task-finished": "already_terminal",
            "task-unsupported": "unsupported",
        }
        assert guardian_sentinel.read_text(encoding="utf-8") == "not a consumer input"
        assert json.loads((jobs / "task-active.json").read_text())["state"] == "running"
        assert stderr == ""


def test_notify_systemd_uses_explicit_filesystem_datagram_path():
    with tempfile.TemporaryDirectory() as temporary:
        path = str(Path(temporary) / "notify.sock")
        receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            receiver.bind(path)
            receiver.settimeout(1)
            assert systemd_notify.notify_systemd("READY=1", path) is None
            assert receiver.recv(4096) == b"READY=1"
        finally:
            receiver.close()


def test_notify_systemd_supports_systemd_abstract_socket_names():
    name = f"\0cointelprofessional-test-{os.getpid()}-{time.time_ns()}"
    receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        receiver.bind(name)
        receiver.settimeout(1)
        systemd_notify.notify_systemd("WATCHDOG=1", "@" + name[1:])
        assert receiver.recv(4096) == b"WATCHDOG=1"
    finally:
        receiver.close()


def test_gateway_supervisor_restarts_dead_poll_child():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        pid_log = root / "poll-pids"
        source = f'''\
import os
from pathlib import Path
from survival import gateway

root = Path({str(root)!r})
pid_log = Path({str(pid_log)!r})

def get_updates(**_arguments):
    with pid_log.open("a", encoding="utf-8") as output:
        output.write(str(os.getpid()) + "\\n")
        output.flush()
        os.fsync(output.fileno())
    os._exit(0)

gateway.main(
    root, set(), lambda *_arguments: True, lambda *_arguments: None,
    degraded_response_deadline_seconds=1.0,
    poll_seconds=0.05,
    long_poll_seconds=0.05,
    request_timeout_seconds=0.1,
    outbox_poll_seconds=0.05,
    heartbeat_maximum_age_seconds=0.5,
    get_updates=get_updates,
)
'''
        process = start_python_harness(root, "gateway-restart.py", source)
        try:
            pids = wait_until(
                lambda: read_pid_log(pid_log) if len(read_pid_log(pid_log)) >= 2 else None,
            )
            assert pids[0] != pids[1]
            assert process.poll() is None
        finally:
            stderr = stop_process(process)
        assert stderr == "", stderr


def test_gateway_main_owns_notifications_and_stops_when_polling_wedges():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        notify_path = str(root / "notify.sock")
        receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        receiver.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
        receiver.bind(notify_path)
        source = f'''\
import time
from pathlib import Path
from survival import gateway

calls = 0

def get_updates(**_arguments):
    global calls
    calls += 1
    if calls == 1:
        return []
    while True:
        time.sleep(3600)

gateway.main(
    Path({str(root)!r}), set(), lambda *_arguments: True, lambda *_arguments: None,
    degraded_response_deadline_seconds=1.0,
    poll_seconds=0.02,
    long_poll_seconds=0.02,
    request_timeout_seconds=0.05,
    outbox_poll_seconds=0.05,
    heartbeat_maximum_age_seconds=0.20,
    get_updates=get_updates,
)
'''
        process = start_python_harness(
            root, "gateway-notify.py", source, {"NOTIFY_SOCKET": notify_path},
        )
        try:
            messages = wait_for_notifications(receiver, {"READY=1", "WATCHDOG=1"})
            assert all(sender_pid == process.pid for _message, sender_pid in messages)
            time.sleep(0.5)
            drain_notifications(receiver)
            receiver.settimeout(0.35)
            with unittest.TestCase().assertRaises(socket.timeout):
                receiver.recv(4096)
            assert process.poll() is None
        finally:
            stderr = stop_process(process)
            receiver.close()
        assert stderr == "", stderr


def test_guardian_main_owns_notifications_and_stops_when_request_wedges():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        notify_path = str(root / "notify.sock")
        guardian_path = str(root / "guardian.sock")
        wedge_marker = root / "wedged"
        receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        receiver.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
        receiver.bind(notify_path)
        source = f'''\
import time
from pathlib import Path
from survival import guardian

def wedge(_connection):
    Path({str(wedge_marker)!r}).write_text("wedged", encoding="utf-8")
    while True:
        time.sleep(3600)

guardian.run_loop({{
    "socket_path": {guardian_path!r},
    "store_path": Path({str(root / "state")!r}),
    "gateway_uid": {os.getuid()},
    "user_manager_uid": {os.getuid()},
    "guardian_poll_seconds": 0.05,
    "adapters": {{}},
}}, on_accept=wedge)
'''
        process = start_python_harness(
            root, "guardian-notify.py", source, {"NOTIFY_SOCKET": notify_path},
        )
        client = None
        try:
            messages = wait_for_notifications(receiver, {"READY=1", "WATCHDOG=1"})
            assert all(sender_pid == process.pid for _message, sender_pid in messages)
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.connect(guardian_path)
            wait_until(wedge_marker.exists)
            time.sleep(0.2)
            drain_notifications(receiver)
            receiver.settimeout(1.25)
            with unittest.TestCase().assertRaises(socket.timeout):
                receiver.recv(4096)
            assert process.poll() is None
        finally:
            if client is not None:
                client.close()
            stderr = stop_process(process)
            receiver.close()
        assert stderr == ""


def test_guardian_consumes_socket_activation_without_unlinking_the_socket():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        guardian_path = str(root / "guardian.sock")
        notify_path = str(root / "notify.sock")
        accepted_marker = root / "accepted"
        receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        receiver.bind(notify_path)
        source = f'''\
import os
import socket
from pathlib import Path
from survival import guardian

listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
listener.bind({guardian_path!r})
listener.listen(5)
descriptor = listener.detach()
if descriptor != 3:
    os.dup2(descriptor, 3)
    os.close(descriptor)
os.set_inheritable(3, True)
os.environ["LISTEN_PID"] = str(os.getpid())
os.environ["LISTEN_FDS"] = "1"
os.environ["LISTEN_FDNAMES"] = "guardian"

def accept_once(_connection):
    Path({str(accepted_marker)!r}).write_text("accepted", encoding="utf-8")
    raise KeyboardInterrupt

guardian.run_loop({{
    "socket_path": {guardian_path!r},
    "store_path": Path({str(root / "state")!r}),
    "gateway_uid": {os.getuid()},
    "user_manager_uid": {os.getuid()},
    "guardian_poll_seconds": 0.05,
    "adapters": {{}},
}}, on_accept=accept_once)
'''
        process = start_python_harness(
            root, "guardian-activation.py", source, {"NOTIFY_SOCKET": notify_path},
        )
        client = None
        stderr = ""
        try:
            wait_for_notifications(receiver, {"READY=1"})
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.connect(guardian_path)
            wait_until(accepted_marker.exists)
            _stdout, stderr_bytes = process.communicate(timeout=3)
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            assert process.returncode == 0
            assert Path(guardian_path).is_socket()
        finally:
            if client is not None:
                client.close()
            if process.poll() is None:
                stderr = stop_process(process)
            receiver.close()
        assert stderr == ""


def test_guardian_peer_uid_boundary_uses_real_unix_credentials():
    guardian_end, client_end = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        assert guardian.peer_uid(guardian_end) == os.getuid()
        guardian.authorize_peer(os.getuid(), os.getuid())
        with unittest.TestCase().assertRaises(PermissionError):
            guardian.authorize_peer(os.getuid() + 1, os.getuid())
    finally:
        guardian_end.close()
        client_end.close()


def write_fake_command_backend(root):
    fake_directory = root / "fake-bin"
    state_directory = root / "fake-state"
    fake_directory.mkdir()
    state_directory.mkdir()
    backend = fake_directory / "backend"
    backend.write_text(
        '''#!/usr/bin/env python3
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

name = Path(sys.argv[0]).name
state = Path(os.environ["FAKE_STATE_DIRECTORY"])
with (state / "trace.jsonl").open("a", encoding="utf-8") as output:
    output.write(json.dumps([name, *sys.argv[1:]], separators=(",", ":")) + "\\n")

if name == "getent":
    kind, identity = sys.argv[1:3]
    marker = state / f"{kind}-{identity}"
    if marker.exists():
        if kind == "passwd":
            print(f"{identity}:x:991:991::/nonexistent:/usr/sbin/nologin")
        else:
            print(f"{identity}:x:991:")
        raise SystemExit(0)
    raise SystemExit(2)
if name == "groupadd":
    (state / f"group-{sys.argv[-1]}").touch()
    raise SystemExit(0)
if name == "useradd":
    identity = sys.argv[-1]
    (state / f"passwd-{identity}").touch()
    (state / f"group-{identity}").touch()
    raise SystemExit(0)
if name == "usermod":
    raise SystemExit(0)
if name == "id":
    option, identity = sys.argv[1:3]
    if option == "-u":
        print("991" if identity == "cointelprofessional" else "1000")
    elif option == "-gn":
        print("cointelprofessional" if identity == "cointelprofessional" else identity)
    else:
        raise SystemExit(2)
    raise SystemExit(0)
if name == "install":
    failure_suffix = os.environ.get("FAKE_INSTALL_FAILURE_SUFFIX")
    if failure_suffix and sys.argv[-1].endswith(failure_suffix):
        print("injected install failure", file=sys.stderr)
        raise SystemExit(73)
    arguments = []
    index = 1
    while index < len(sys.argv):
        if sys.argv[index] in {"-o", "-g"}:
            index += 2
            continue
        arguments.append(sys.argv[index])
        index += 1
    raise SystemExit(subprocess.run(["/usr/bin/install", *arguments], check=False).returncode)
if name == "systemd-analyze":
    if os.environ.get("FAKE_VERIFY_FAILURE") == "1":
        print("injected verification failure", file=sys.stderr)
        raise SystemExit(74)
    release_root = Path(sys.argv[2]).parents[2]
    required_release_entries = (
        "survival/checkpoint.py",
        "survival/gateway.py",
        "survival/guardian.py",
        "scripts/cointelprofessional-checkpoint",
        "scripts/cointelprofessional-gateway",
        "scripts/cointelprofessional-guardian",
        "config/survival-lifecycle.json",
        "services/system/cointelprofessional-checkpoint.service",
        "services/system/cointelprofessional-survival.slice",
        "services/system/cointelprofessional-gateway.service",
        "services/system/cointelprofessional-guardian.socket",
        "services/system/cointelprofessional-guardian.service",
    )
    if (
        release_root.stat().st_mode & 0o777 != 0o755
        or any(not (release_root / relative).is_file() for relative in required_release_entries)
    ):
        print("release was not complete before verification", file=sys.stderr)
        raise SystemExit(76)
    raise SystemExit(0)
if name == "mv":
    if (
        os.environ.get("FAKE_PRE_COMMIT_ABRUPT") == "1"
        and sys.argv[-1].endswith("/current")
    ):
        os.kill(os.getppid(), signal.SIGKILL)
        raise SystemExit(78)
    if os.environ.get("FAKE_COMMIT_FAILURE") == "1" and sys.argv[-1].endswith("/current"):
        print("injected commit failure", file=sys.stderr)
        raise SystemExit(75)
    result = subprocess.run(["/usr/bin/mv", *sys.argv[1:]], check=False)
    if (
        result.returncode == 0
        and os.environ.get("FAKE_POST_COMMIT_INTERRUPTION") == "1"
        and sys.argv[-1].endswith("/current")
    ):
        print("injected post-commit interruption", file=sys.stderr)
        raise SystemExit(77)
    raise SystemExit(result.returncode)
if name == "ln":
    result = subprocess.run(["/usr/bin/ln", *sys.argv[1:]], check=False)
    destination = sys.argv[-1]
    if result.returncode == 0 and "/etc/systemd/system/" in destination:
        counter = state / "wrapper-count"
        value = int(counter.read_text()) + 1 if counter.exists() else 1
        counter.write_text(str(value))
        if os.environ.get("FAKE_WRAPPER_KILL_INDEX") == str(value):
            os.kill(os.getppid(), signal.SIGKILL)
    raise SystemExit(result.returncode)
if name == "systemctl":
    raise SystemExit(0)
raise SystemExit(127)
''',
        encoding="utf-8",
    )
    backend.chmod(0o755)
    for name in (
        "getent", "groupadd", "useradd", "usermod", "id", "install",
        "systemd-analyze", "systemctl", "mv", "ln",
    ):
        (fake_directory / name).symlink_to(backend)
    return fake_directory, state_directory


def invoke_fake_installer(
    installer, fake_directory, state_directory, image, arguments=(),
    extra_environment=None,
):
    environment = os.environ.copy()
    environment.update({
        "PATH": str(fake_directory) + ":/usr/bin:/bin",
        "FAKE_STATE_DIRECTORY": str(state_directory),
        "COINTELPROFESSIONAL_INSTALL_ROOT": str(image),
    })
    if extra_environment is not None:
        environment.update(extra_environment)
    return subprocess.run(
        [str(installer), *arguments],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
        check=False,
    )


def run_fake_installer(
    root, *arguments, installer=installer_path, extra_environment=None,
):
    fake_directory, state_directory = write_fake_command_backend(root)
    image = root / "image"
    configuration = image / "etc/cointelprofessional"
    configuration.mkdir(parents=True, exist_ok=True)
    allowed = configuration / "allowed_user_ids"
    if not allowed.exists() and not allowed.is_symlink():
        allowed.write_text("42\n", encoding="utf-8")
        allowed.chmod(0o600)
    result = invoke_fake_installer(
        installer, fake_directory, state_directory, image, arguments,
        extra_environment,
    )
    trace_path = state_directory / "trace.jsonl"
    trace = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    return result, trace, image, state_directory


def installed_tree_digest(root):
    values = []
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            values.append((relative, "symlink", os.readlink(path)))
        elif path.is_dir():
            values.append((relative, "directory", path.stat().st_mode & 0o7777))
        elif path.is_file():
            values.append((
                relative,
                path.stat().st_mode & 0o7777,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            ))
    return values


def copy_installer_source(root):
    source_root = root / "source"
    for relative in installer_source_paths:
        destination = source_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base / relative, destination)
    return source_root, source_root / "scripts/install-survival-plane"


def prepare_release_update(root):
    source_root, copied_installer = copy_installer_source(root)
    first, _trace, image, state = run_fake_installer(
        root, installer=copied_installer,
    )
    assert first.returncode == 0, first.stderr
    prior_digest = installed_tree_digest(image)
    with (source_root / "survival/gateway.py").open("a", encoding="utf-8") as output:
        output.write("\nrelease_marker = 'candidate-two'\n")
    with (
        source_root / "services/system/cointelprofessional-guardian.service"
    ).open("a", encoding="utf-8") as output:
        output.write("\n# candidate-two\n")
    return copied_installer, image, state, prior_digest


def assert_failed_update_is_invisible(image, prior_digest):
    assert installed_tree_digest(image) == prior_digest
    authoritative_gateway = (
        image / "usr/local/lib/cointelprofessional-survival/current/survival/gateway.py"
    )
    assert b"candidate-two" not in authoritative_gateway.read_bytes()
    authoritative_guardian_unit = (
        image / "etc/systemd/system/cointelprofessional-guardian.service"
    )
    assert b"candidate-two" not in authoritative_guardian_unit.read_bytes()


def published_installation_paths(image):
    snapshot = image / "usr/local/lib/cointelprofessional-survival"
    return (
        snapshot / "current",
        image / "etc/systemd/system/cointelprofessional-checkpoint.service",
        image / "etc/systemd/system/cointelprofessional-survival.slice",
        image / "etc/systemd/system/cointelprofessional-gateway.service",
        image / "etc/systemd/system/cointelprofessional-guardian.socket",
        image / "etc/systemd/system/cointelprofessional-guardian.service",
    )


def test_installer_is_idempotent_and_install_only_by_default():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        result, first_trace, image, state = run_fake_installer(root)
        assert result.returncode == 0, result.stderr
        first_digest = installed_tree_digest(image)
        time_config = image / "etc/cointelprofessional/time.cfg"
        time_config.write_text(
            time_config.read_text(encoding="utf-8").replace(
                "poll_seconds = 1", "poll_seconds = 1.5",
            ),
            encoding="utf-8",
        )
        expected_digest = installed_tree_digest(image)
        time_config.chmod(0o640)
        edited_digest = installed_tree_digest(image)
        environment = os.environ.copy()
        environment.update({
            "PATH": str(root / "fake-bin") + ":/usr/bin:/bin",
            "FAKE_STATE_DIRECTORY": str(state),
            "COINTELPROFESSIONAL_INSTALL_ROOT": str(image),
        })
        second = subprocess.run(
            [str(installer_path)], capture_output=True, text=True,
            stdin=subprocess.DEVNULL, env=environment, timeout=10, check=False,
        )
        assert second.returncode == 0, second.stderr
        second_trace = [
            json.loads(line)
            for line in (state / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        assert edited_digest != first_digest
        assert installed_tree_digest(image) == expected_digest
        assert "poll_seconds = 1.5" in time_config.read_text(encoding="utf-8")
        assert time_config.stat().st_mode & 0o777 == 0o644
        assert not any(call[0] == "systemctl" for call in second_trace)
        assert sum(call[0] == "groupadd" for call in second_trace) == 2
        assert sum(call[0] == "useradd" for call in second_trace) == 1
        assert ["groupadd", "--system", "cointelprofessional_command"] in first_trace
        assert ["groupadd", "--system", "agent_ecosystem_io"] in first_trace
        assert [
            "useradd", "--system", "--user-group", "--home-dir", "/nonexistent",
            "--shell", "/usr/sbin/nologin", "cointelprofessional",
        ] in first_trace
        assert [
            "usermod", "--append", "--groups", "cointelprofessional_command",
            "cointelprofessional",
        ] in first_trace
        assert any(call[:3] == ["usermod", "--append", "--groups"] and call[-1] == "david" for call in first_trace)


def test_installer_realizes_exact_snapshot_modes_paths_and_dynamic_uids():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        result, trace, image, _state = run_fake_installer(root)
        assert result.returncode == 0, result.stderr
        snapshot = image / "usr/local/lib/cointelprofessional-survival"
        assert (snapshot / "current/survival/checkpoint.py").read_bytes() == (
            base / "survival/checkpoint.py"
        ).read_bytes()
        assert (snapshot / "current/scripts/cointelprofessional-checkpoint").read_bytes() == (
            base / "scripts/cointelprofessional-checkpoint"
        ).read_bytes()
        assert (snapshot / "current/survival/gateway.py").read_bytes() == (base / "survival/gateway.py").read_bytes()
        assert (snapshot / "current/scripts/cointelprofessional-gateway").read_bytes() == (
            base / "scripts/cointelprofessional-gateway"
        ).read_bytes()
        assert (snapshot / "current/scripts/cointelprofessional-gateway").stat().st_mode & 0o777 == 0o755
        assert (snapshot / "current/scripts/cointelprofessional-checkpoint").stat().st_mode & 0o777 == 0o755
        store = image / "var/lib/cointelprofessional"
        assert store.stat().st_mode & 0o777 == 0o755
        assert (store / "inbox").stat().st_mode & 0o7777 == 0o2750
        assert (store / "outbox/critical").stat().st_mode & 0o7777 == 0o2750
        for relative in (
            "commands", "gateway", "gateway_commands", "acks", "heartbeats",
            "dispositions", "quarantine", "gateway/critical-delivery",
            "gateway/critical-attempts", "gateway/data-health-incidents",
            "gateway/delivery-health-incidents",
        ):
            assert (store / relative).stat().st_mode & 0o777 == 0o700
        for relative in (
            "lifecycle", "lifecycle-runtime", "lifecycle-completions",
            "lifecycle-progress", "lifecycle-result-quarantine",
            "lifecycle-transitions",
        ):
            assert (store / relative).stat().st_mode & 0o777 == 0o700
        assert (store / "checkpoint-requests").stat().st_mode & 0o777 == 0o750
        assert (store / "checkpoint-results").stat().st_mode & 0o777 == 0o750
        assert (store / "policy").stat().st_mode & 0o7777 == 0o2750
        assert (image / "run/cointelprofessional").stat().st_mode & 0o777 == 0o750
        assert (image / "etc/cointelprofessional").stat().st_mode & 0o777 == 0o750
        guardian_environment = image / "etc/cointelprofessional/guardian.env"
        assert guardian_environment.stat().st_mode & 0o777 == 0o600
        assert guardian_environment.read_text(encoding="utf-8") == (
            "GUARDIAN_GATEWAY_UID=991\nUSER_MANAGER_UID=1000\n"
        )
        incident_destination = image / "etc/cointelprofessional/incident_destination.json"
        assert incident_destination.stat().st_mode & 0o777 == 0o600
        assert json.loads(incident_destination.read_text(encoding="utf-8")) == {
            "schema_version": 1,
            "telegram_user_id": 42,
            "chat_id": 42,
        }
        time_config = image / "etc/cointelprofessional/time.cfg"
        assert time_config.stat().st_mode & 0o777 == 0o644
        assert time_config.read_bytes() == (base / "config/time.cfg").read_bytes()
        assert not (snapshot / "current/config/time.cfg").exists()
        assert not (image / "etc/cointelprofessional/telegram_bot_token").exists()
        assert (
            image / "etc/cointelprofessional/allowed_user_ids"
        ).read_text(encoding="utf-8") == "42\n"
        assert [
            "install", "-d", "-o", "root", "-g", "root",
            "-m", "0755", str(store),
        ] in trace
        assert [
            "install", "-d", "-o", "cointelprofessional", "-g", "agent_ecosystem_io",
            "-m", "2750", str(store / "inbox"),
        ] in trace
        assert [
            "install", "-d", "-o", "root", "-g", "cointelprofessional",
            "-m", "2750", str(store / "outbox/critical"),
        ] in trace
        assert [
            "install", "-d", "-o", "root", "-g", "cointelprofessional_command",
            "-m", "0750", str(image / "run/cointelprofessional"),
        ] in trace
        assert [
            "install", "-d", "-o", "root", "-g", "cointelprofessional",
            "-m", "0750", str(image / "etc/cointelprofessional"),
        ] in trace
        assert any(
            call[:7] == ["install", "-o", "root", "-g", "root", "-m", "0600"]
            and "/.incident_destination.candidate." in call[-1]
            for call in trace
        )
        analyze_calls = [call for call in trace if call[0] == "systemd-analyze"]
        assert len(analyze_calls) == 1
        assert analyze_calls[0][1] == "verify"


def test_installer_requires_one_exact_authorized_incident_identity():
    for source in (None, "", "42\n43\n", "true\n", "-1\n", "042\n"):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_directory, state = write_fake_command_backend(root)
            image = root / "image"
            if source is not None:
                configuration = image / "etc/cointelprofessional"
                configuration.mkdir(parents=True)
                (configuration / "allowed_user_ids").write_text(
                    source, encoding="utf-8",
                )

            result = invoke_fake_installer(
                installer_path, fake_directory, state, image,
            )

            assert result.returncode != 0
            assert "incident destination" in result.stderr
            assert not (
                image / "etc/cointelprofessional/incident_destination.json"
            ).exists()


def test_installer_enable_is_explicit_and_unknown_arguments_are_not_echoed():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        result, trace, _image, _state = run_fake_installer(root, "--enable")
        assert result.returncode == 0, result.stderr
        assert [call for call in trace if call[0] == "systemctl"] == [
            ["systemctl", "daemon-reload"],
            [
                "systemctl", "enable", "--now",
                "cointelprofessional-checkpoint.service",
                "cointelprofessional-guardian.socket",
                "cointelprofessional-guardian.service",
                "cointelprofessional-gateway.service",
            ],
        ]
        rejected = subprocess.run(
            [str(installer_path), "credential-value-must-not-leak"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=5, check=False,
        )
        assert rejected.returncode == 64
        assert "credential-value-must-not-leak" not in rejected.stderr


def test_installer_construction_failure_preserves_the_authoritative_release():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        installer, image, state, prior_digest = prepare_release_update(root)
        for suffix in (
            "/survival/checkpoint.py",
            "/scripts/cointelprofessional-checkpoint",
            "/services/system/cointelprofessional-checkpoint.service",
        ):
            result = invoke_fake_installer(
                installer, root / "fake-bin", state, image,
                extra_environment={"FAKE_INSTALL_FAILURE_SUFFIX": suffix},
            )
            assert result.returncode == 73
            assert_failed_update_is_invisible(image, prior_digest)


def test_installer_verification_failure_preserves_the_authoritative_release():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        installer, image, state, prior_digest = prepare_release_update(root)
        result = invoke_fake_installer(
            installer, root / "fake-bin", state, image,
            extra_environment={"FAKE_VERIFY_FAILURE": "1"},
        )
        assert result.returncode == 74
        assert_failed_update_is_invisible(image, prior_digest)


def test_installer_precommit_failures_do_not_repair_authoritative_timing_policy():
    for failure, returncode in (
        ({"FAKE_VERIFY_FAILURE": "1"}, 74),
        ({"FAKE_COMMIT_FAILURE": "1"}, 75),
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            installer, image, state, _prior_digest = prepare_release_update(root)
            time_config = image / "etc/cointelprofessional/time.cfg"
            time_config.chmod(0o640)
            prior_digest = installed_tree_digest(image)

            result = invoke_fake_installer(
                installer,
                root / "fake-bin",
                state,
                image,
                extra_environment=failure,
            )

            assert result.returncode == returncode
            assert time_config.stat().st_mode & 0o777 == 0o640
            assert_failed_update_is_invisible(image, prior_digest)


def test_installer_commit_failure_preserves_the_authoritative_release():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        installer, image, state, prior_digest = prepare_release_update(root)
        result = invoke_fake_installer(
            installer, root / "fake-bin", state, image,
            extra_environment={"FAKE_COMMIT_FAILURE": "1"},
        )
        assert result.returncode == 75
        assert_failed_update_is_invisible(image, prior_digest)


def test_installer_rejects_symlinked_or_nonregular_timing_policy_without_mutation():
    for kind in ("symlink", "directory"):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_directory, state = write_fake_command_backend(root)
            image = root / "image"
            configuration = image / "etc/cointelprofessional"
            configuration.mkdir(parents=True)
            timing_path = configuration / "time.cfg"
            if kind == "symlink":
                sentinel = root / "outside-time.cfg"
                sentinel.write_text("outside\n", encoding="utf-8")
                sentinel.chmod(0o600)
                timing_path.symlink_to(sentinel)
            else:
                timing_path.mkdir()
                timing_path.chmod(0o700)

            result = invoke_fake_installer(
                installer_path, fake_directory, state, image,
            )

            assert result.returncode == 1
            assert "timing policy path" in result.stderr
            if kind == "symlink":
                assert sentinel.read_text(encoding="utf-8") == "outside\n"
                assert sentinel.stat().st_mode & 0o777 == 0o600
            else:
                assert timing_path.is_dir()
                assert timing_path.stat().st_mode & 0o777 == 0o700


def test_installer_initial_commit_failure_leaves_no_published_wrappers():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        result, _trace, image, _state = run_fake_installer(
            root,
            extra_environment={"FAKE_COMMIT_FAILURE": "1"},
        )
        assert result.returncode == 75
        snapshot = image / "usr/local/lib/cointelprofessional-survival"
        paths = published_installation_paths(image)
        assert not paths[0].exists() and not paths[0].is_symlink()
        assert all(path.is_symlink() and not path.exists() for path in paths[1:])
        assert list((snapshot / "releases").iterdir()) == []


def test_installer_abrupt_pre_commit_interruption_publishes_no_wrappers():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        result, _trace, image, _state = run_fake_installer(
            root,
            extra_environment={"FAKE_PRE_COMMIT_ABRUPT": "1"},
        )
        assert result.returncode == -signal.SIGKILL
        snapshot = image / "usr/local/lib/cointelprofessional-survival"
        paths = published_installation_paths(image)
        assert not paths[0].exists() and not paths[0].is_symlink()
        assert all(path.is_symlink() and not path.exists() for path in paths[1:])
        releases = list((snapshot / "releases").glob("release-*"))
        assert len(releases) == 1
        release = releases[0]
        assert release.stat().st_mode & 0o777 == 0o755
        assert (release / "survival/gateway.py").read_bytes() == (
            base / "survival/gateway.py"
        ).read_bytes()
        assert (release / "survival/checkpoint.py").read_bytes() == (
            base / "survival/checkpoint.py"
        ).read_bytes()
        guardian_unit = release / "services/system/cointelprofessional-guardian.service"
        assert guardian_unit.read_bytes() == (
            base / "services/system/cointelprofessional-guardian.service"
        ).read_bytes()


def test_first_install_interruption_at_each_wrapper_keeps_authoritative_root_absent():
    for wrapper_index in range(1, 6):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result, _trace, image, state = run_fake_installer(
                root,
                extra_environment={"FAKE_WRAPPER_KILL_INDEX": str(wrapper_index)},
            )
            assert result.returncode == -signal.SIGKILL
            snapshot = image / "usr/local/lib/cointelprofessional-survival"
            assert not (snapshot / "current").exists()
            for unit_path in published_installation_paths(image)[1:]:
                assert not unit_path.exists()
            retry = invoke_fake_installer(
                installer_path, root / "fake-bin", state, image,
            )
            assert retry.returncode == 0, retry.stderr
            assert (snapshot / "current").resolve().is_dir()
            assert all(path.exists() for path in published_installation_paths(image))


def test_installer_post_commit_interruption_keeps_a_complete_release_visible():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        installer, image, state, _prior_digest = prepare_release_update(root)
        snapshot = image / "usr/local/lib/cointelprofessional-survival"
        prior_releases = set((snapshot / "releases").iterdir())
        result = invoke_fake_installer(
            installer, root / "fake-bin", state, image,
            extra_environment={"FAKE_POST_COMMIT_INTERRUPTION": "1"},
        )
        assert result.returncode == 77
        assert (snapshot / "current").resolve().is_dir()
        assert b"candidate-two" in (snapshot / "current/survival/gateway.py").read_bytes()
        assert (snapshot / "current/survival/checkpoint.py").read_bytes() == (
            base / "survival/checkpoint.py"
        ).read_bytes()
        guardian_unit = image / "etc/systemd/system/cointelprofessional-guardian.service"
        assert b"candidate-two" in guardian_unit.read_bytes()
        assert prior_releases <= set((snapshot / "releases").iterdir())


def test_installer_rejects_a_release_with_tampered_root_metadata():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        result, _trace, image, state = run_fake_installer(root)
        assert result.returncode == 0, result.stderr
        snapshot = image / "usr/local/lib/cointelprofessional-survival"
        release = (snapshot / "current").resolve()
        current_target = os.readlink(snapshot / "current")
        release.chmod(0o700)
        result = invoke_fake_installer(
            installer_path, root / "fake-bin", state, image,
        )
        assert result.returncode == 1
        assert "content identity" in result.stderr
        assert os.readlink(snapshot / "current") == current_target


def test_installer_rejects_tampered_checkpoint_consumer_content():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        result, _trace, image, state = run_fake_installer(root)
        assert result.returncode == 0, result.stderr
        snapshot = image / "usr/local/lib/cointelprofessional-survival"
        release = (snapshot / "current").resolve()
        current_target = os.readlink(snapshot / "current")
        (release / "survival/checkpoint.py").write_text(
            "tampered checkpoint consumer\n", encoding="utf-8",
        )

        result = invoke_fake_installer(
            installer_path, root / "fake-bin", state, image,
        )

        assert result.returncode == 1
        assert "content identity" in result.stderr
        assert os.readlink(snapshot / "current") == current_target


def load_tests(_loader, _tests, _pattern):
    functions = [
        value for name, value in globals().items()
        if name.startswith("test_") and callable(value)
    ]
    return unittest.TestSuite(
        unittest.FunctionTestCase(function) for function in functions
    )


if __name__ == "__main__":
    unittest.main()
