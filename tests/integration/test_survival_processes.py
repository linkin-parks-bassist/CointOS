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

from survival import guardian, systemd_notify


base = Path(__file__).resolve().parent.parent.parent
unit_directory = base / "services" / "system"
installer_path = base / "scripts" / "install-survival-plane"
installer_source_paths = (
    "scripts/install-survival-plane",
    "scripts/cointelprofessional-gateway",
    "scripts/cointelprofessional-guardian",
    "survival/__init__.py",
    "survival/gateway.py",
    "survival/guardian.py",
    "survival/json_codec.py",
    "survival/lifecycle.py",
    "survival/protocol.py",
    "survival/records.py",
    "survival/system_control.py",
    "survival/systemd_notify.py",
    "survival/telegram_api.py",
    "docs/operations.md",
    "config/time.cfg",
    "services/system/cointelprofessional-survival.slice",
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
        "cointelprofessional-gateway.service": "survival.gateway",
        "cointelprofessional-guardian.service": "survival.guardian",
    }
    for name, module in modules.items():
        text = load_unit(name)
        assert f"ExecStart=/usr/bin/python3 -m {module}" in text
        assert "WorkingDirectory=/usr/local/lib/cointelprofessional-survival" in text
        assert "%h" not in text
        assert "/home/" not in text
        assert "agent-ecosystem" not in text


def test_units_use_systemd_notification_and_local_documentation_paths():
    for path in unit_directory.glob("cointelprofessional-*"):
        text = path.read_text(encoding="utf-8")
        assert "Environment=NOTIFY_SOCKET=" not in text
        assert "github.com" not in text
    assert "Documentation=file:///usr/local/lib/cointelprofessional-survival/docs/operations.md" in load_unit(
        "cointelprofessional-gateway.service",
    )


def test_units_project_task_3_and_4_paths_and_groups():
    gateway_text = load_unit("cointelprofessional-gateway.service")
    assert "SupplementaryGroups=cointelprofessional_command agent_ecosystem_io" in gateway_text
    assert "Environment=GUARDIAN_SOCKET_PATH=/run/cointelprofessional/guardian.sock" in gateway_text
    assert "Environment=SURVIVAL_STORE_DIR=/var/lib/cointelprofessional" in gateway_text
    assert "Environment=TIME_CONFIG_PATH=/etc/cointelprofessional/time.cfg" in gateway_text
    assert "Environment=CREDENTIALS_DIRECTORY=" not in gateway_text
    guardian_text = load_unit("cointelprofessional-guardian.service")
    assert "EnvironmentFile=/etc/cointelprofessional/guardian.env" in guardian_text
    assert "Environment=GUARDIAN_SOCKET_PATH=/run/cointelprofessional/guardian.sock" in guardian_text
    assert "Environment=SURVIVAL_STORE_DIR=/var/lib/cointelprofessional" in guardian_text


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
        assert stderr == ""


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
        assert stderr == ""


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
        "survival/gateway.py",
        "survival/guardian.py",
        "scripts/cointelprofessional-gateway",
        "scripts/cointelprofessional-guardian",
        "docs/operations.md",
        "config/time.cfg",
        "config/guardian.env",
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
if name == "systemctl":
    raise SystemExit(0)
raise SystemExit(127)
''',
        encoding="utf-8",
    )
    backend.chmod(0o755)
    for name in (
        "getent", "groupadd", "useradd", "usermod", "id", "install",
        "systemd-analyze", "systemctl", "mv",
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
        image / "usr/local/lib/cointelprofessional-survival/survival/gateway.py"
    )
    assert b"candidate-two" not in authoritative_gateway.read_bytes()
    authoritative_guardian_unit = (
        image / "etc/systemd/system/cointelprofessional-guardian.service"
    )
    assert b"candidate-two" not in authoritative_guardian_unit.read_bytes()


def test_installer_is_idempotent_and_install_only_by_default():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        result, first_trace, image, state = run_fake_installer(root)
        assert result.returncode == 0, result.stderr
        first_digest = installed_tree_digest(image)
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
        assert first_digest == installed_tree_digest(image)
        assert not any(call[0] == "systemctl" for call in second_trace)
        assert sum(call[0] == "groupadd" for call in second_trace) == 2
        assert sum(call[0] == "useradd" for call in second_trace) == 1
        assert ["groupadd", "--system", "cointelprofessional_command"] in first_trace
        assert ["groupadd", "--system", "agent_ecosystem_io"] in first_trace
        assert [
            "useradd", "--system", "--user-group", "--home-dir", "/nonexistent",
            "--shell", "/usr/sbin/nologin", "cointelprofessional",
        ] in first_trace
        assert any(call[:3] == ["usermod", "--append", "--groups"] and call[-1] == "cointelprofessional" for call in first_trace)
        assert any(call[:3] == ["usermod", "--append", "--groups"] and call[-1] == "david" for call in first_trace)


def test_installer_realizes_exact_snapshot_modes_paths_and_dynamic_uids():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        result, trace, image, _state = run_fake_installer(root)
        assert result.returncode == 0, result.stderr
        snapshot = image / "usr/local/lib/cointelprofessional-survival"
        assert (snapshot / "survival/gateway.py").read_bytes() == (base / "survival/gateway.py").read_bytes()
        assert (snapshot / "scripts/cointelprofessional-gateway").read_bytes() == (
            base / "scripts/cointelprofessional-gateway"
        ).read_bytes()
        assert (snapshot / "docs/operations.md").read_bytes() == (base / "docs/operations.md").read_bytes()
        assert (snapshot / "scripts/cointelprofessional-gateway").stat().st_mode & 0o777 == 0o755
        assert (image / "var/lib/cointelprofessional").stat().st_mode & 0o7777 == 0o2770
        assert (image / "run/cointelprofessional").stat().st_mode & 0o777 == 0o750
        assert (image / "etc/cointelprofessional").stat().st_mode & 0o777 == 0o750
        guardian_environment = image / "etc/cointelprofessional/guardian.env"
        assert guardian_environment.stat().st_mode & 0o777 == 0o600
        assert guardian_environment.read_text(encoding="utf-8") == (
            "GUARDIAN_GATEWAY_UID=991\nUSER_MANAGER_UID=1000\n"
        )
        assert not (image / "etc/cointelprofessional/telegram_bot_token").exists()
        assert not (image / "etc/cointelprofessional/allowed_user_ids").exists()
        assert [
            "install", "-d", "-o", "root", "-g", "agent_ecosystem_io",
            "-m", "2770", str(image / "var/lib/cointelprofessional"),
        ] in trace
        assert [
            "install", "-d", "-o", "root", "-g", "cointelprofessional_command",
            "-m", "0750", str(image / "run/cointelprofessional"),
        ] in trace
        assert [
            "install", "-d", "-o", "root", "-g", "cointelprofessional",
            "-m", "0750", str(image / "etc/cointelprofessional"),
        ] in trace
        analyze_calls = [call for call in trace if call[0] == "systemd-analyze"]
        assert len(analyze_calls) == 1
        assert analyze_calls[0][1] == "verify"


def test_installer_enable_is_explicit_and_unknown_arguments_are_not_echoed():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        result, trace, _image, _state = run_fake_installer(root, "--enable")
        assert result.returncode == 0, result.stderr
        assert [call for call in trace if call[0] == "systemctl"] == [
            ["systemctl", "daemon-reload"],
            [
                "systemctl", "enable", "--now",
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
        result = invoke_fake_installer(
            installer, root / "fake-bin", state, image,
            extra_environment={
                "FAKE_INSTALL_FAILURE_SUFFIX": "/survival/telegram_api.py",
            },
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


def test_installer_initial_commit_failure_leaves_no_published_wrappers():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        result, _trace, image, _state = run_fake_installer(
            root,
            extra_environment={"FAKE_COMMIT_FAILURE": "1"},
        )
        assert result.returncode == 75
        snapshot = image / "usr/local/lib/cointelprofessional-survival"
        published_paths = (
            snapshot / "current",
            snapshot / "survival",
            snapshot / "scripts",
            snapshot / "docs",
            image / "etc/cointelprofessional/time.cfg",
            image / "etc/cointelprofessional/guardian.env",
            image / "etc/systemd/system/cointelprofessional-survival.slice",
            image / "etc/systemd/system/cointelprofessional-gateway.service",
            image / "etc/systemd/system/cointelprofessional-guardian.socket",
            image / "etc/systemd/system/cointelprofessional-guardian.service",
        )
        assert not any(path.exists() or path.is_symlink() for path in published_paths)
        assert list((snapshot / "releases").iterdir()) == []


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
        assert b"candidate-two" in (snapshot / "survival/gateway.py").read_bytes()
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
