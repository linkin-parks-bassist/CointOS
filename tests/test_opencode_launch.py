"""Verify actual loaded limits, configuration precedence, and fail-closed launch."""
import copy
import importlib.util
import io
import http.server
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import subprocess
import unittest
from unittest.mock import patch

from ecosystem.opencode_launch import prepare_environment, verify_server_capacity
from ecosystem.inference_capacity import constrain_launch_capacity
from ecosystem.executor import _observe_worker_capacity
from tests.test_inference_enforcement import effective_record

ROOT = Path(__file__).resolve().parents[1]
COMMAND = ["/home/david/.opencode/bin/opencode", "run", "--model", "Lemonade/model-a"]


def _stale_config(base="http://127.0.0.1:13305/v1", output=64000):
    return {"provider": {"Lemonade": {"npm": "@ai-sdk/openai-compatible",
            "options": {"baseURL": base, "apiKey": "private-test-value"},
            "models": {"model-a": {"limit": {"context": 262144, "input": 260000, "output": output}}}}},
            "compaction": {"auto": False}, "permission": "deny", "plugin": []}


def test_stale_inline_limits_are_replaced_without_writing_user_config():
    config = _stale_config()
    env = {"OPENCODE_CONFIG_CONTENT": json.dumps(config)}
    with patch("ecosystem.opencode_launch.derive_capacity", return_value=effective_record()):
        updated, fd, record = prepare_environment(COMMAND, env, ROOT)
    try:
        loaded = json.loads(os.pread(fd, os.fstat(fd).st_size, 0))
        assert loaded["provider"]["Lemonade"]["models"]["model-a"]["limit"] == {
            "context": 4096, "input": 2048, "output": 2048}
        assert loaded["compaction"]["auto"] is True
        assert loaded["small_model"] == "Lemonade/model-a"
        assert loaded["permission"] == "deny"
        assert env["OPENCODE_CONFIG_CONTENT"] == json.dumps(config)
        assert "private-test-value" not in updated["OPENCODE_CONFIG_CONTENT"]
    finally:
        os.close(fd)


def test_managed_proxy_keeps_smaller_admitted_allowance():
    config = _stale_config("http://127.0.0.1:13306/v1", output=128)
    config["provider"]["Lemonade"]["models"]["model-a"]["limit"]["context"] = 4096
    with patch("ecosystem.opencode_launch.derive_capacity", return_value=effective_record()):
        env, fd, record = prepare_environment(COMMAND, {"OPENCODE_CONFIG_CONTENT": json.dumps(config)}, ROOT)
    try:
        loaded = json.loads(os.pread(fd, os.fstat(fd).st_size, 0))
        assert record["effective_output_tokens"] == 2048
        assert record["opencode_output_tokens"] == 128
        assert loaded["provider"]["Lemonade"]["models"]["model-a"]["limit"] == {
            "context": 4096, "input": 3968, "output": 128}
    finally:
        os.close(fd)


def test_managed_stale_allocation_is_rejected():
    config = _stale_config("http://127.0.0.1:13306/v1")
    with patch("ecosystem.opencode_launch.derive_capacity", return_value=effective_record()):
        with unittest.TestCase().assertRaisesRegex(ValueError, "exceeds the live effective context"):
            prepare_environment(COMMAND, {"OPENCODE_CONFIG_CONTENT": json.dumps(config)}, ROOT)


def test_unavailable_capacity_stops_before_configuration_is_created():
    with patch("ecosystem.opencode_launch.derive_capacity", side_effect=ValueError("unavailable")):
        with unittest.TestCase().assertRaisesRegex(ValueError, "unavailable"):
            prepare_environment(COMMAND, {}, ROOT)


def test_ambiguous_or_changing_residency_never_becomes_capacity():
    item = {"id": "model-a", "downloaded": True}
    resident = {"model_name": "model-a", "backend_url": "http://127.0.0.1:9000/v1",
                "pid": 123, "loaded": True, "backend_alive": True}
    for registry, health, refreshed in (
            ([item, item], [resident], [resident]),
            ([item], [resident, resident], [resident]),
            ([item], [resident], [dict(resident, pid=124)])):
        documents = [{"data": registry}, {"all_models_loaded": health},
                     {"all_models_loaded": refreshed}]
        with patch("ecosystem.models._get", side_effect=documents), \
                patch("ecosystem.models._get_backend", return_value={}), \
                patch("ecosystem.executor.process_identity", return_value={"start_ticks": 1}), \
                patch("ecosystem.executor.observe_opencode_backend_capacity") as normalize:
            assert _observe_worker_capacity(ROOT, "model-a", refresh_inventory=True, clock=lambda: 10) is None
            normalize.assert_not_called()


def test_constrained_record_preserves_backend_facts_without_mutation():
    record = effective_record()
    original = copy.deepcopy(record)
    result = constrain_launch_capacity({"model_id": "model-a",
            "context_tokens_per_sequence": 2048, "max_output_tokens": 128}, record)
    assert record == original
    assert result["effective_context_tokens"] == 4096
    assert result["opencode_context_tokens"] == 2048
    assert result["opencode_output_tokens"] == 128
    with unittest.TestCase().assertRaisesRegex(ValueError, "does not fit"):
        constrain_launch_capacity({"model_id": "model-a",
            "context_tokens_per_sequence": 128, "max_output_tokens": 128}, record)


def _read_back(record, actual_context=4096, fresh=None):
    config = {"compaction": {"auto": True}, "small_model": "Lemonade/model-a",
              "agent": {"compaction": {"model": "Lemonade/model-a"}},
              "provider": {"Lemonade": {"options": {"baseURL": "http://127.0.0.1:13305/v1"}}}}
    provider = {"all": [{"id": "Lemonade", "models": {"model-a": {
        "limit": {"context": actual_context, "input": 2048, "output": 2048}}}}]}
    def reply(url, **kwargs):
        return io.StringIO(json.dumps(config if "/config?" in url else provider))
    with patch("urllib.request.urlopen", side_effect=reply), \
            patch("ecosystem.opencode_launch.derive_capacity", return_value=fresh or record):
        verify_server_capacity("http://127.0.0.1:1234", ROOT, record,
                               "http://127.0.0.1:13305/v1", binary=COMMAND[0], root=ROOT)


def test_server_resolved_context_mismatch_is_rejected():
    with unittest.TestCase().assertRaisesRegex(ValueError, "resolved model limits disagree"):
        _read_back(effective_record(), actual_context=262144)


def test_backend_change_during_startup_is_rejected():
    record = effective_record()
    fresh = copy.deepcopy(record)
    fresh["backend_incarnation"]["pid"] += 1
    with unittest.TestCase().assertRaisesRegex(ValueError, "changed during"):
        _read_back(record, fresh=fresh)


def test_real_server_loads_correct_limits_despite_stale_configuration_without_inference():
    script = ROOT / "scripts/opencode_observable.py"
    sys.path.insert(0, str(script.parent))
    spec = importlib.util.spec_from_file_location("observable_capacity_test", script)
    observable = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(observable)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        env = {key: value for key, value in os.environ.items() if not key.startswith("OPENCODE_")}
        env.update(XDG_CONFIG_HOME=str(root / "config"), XDG_DATA_HOME=str(root / "data"),
                   XDG_CACHE_HOME=str(root / "cache"), XDG_STATE_HOME=str(root / "state"),
                   OPENCODE_CONFIG_CONTENT=json.dumps(_stale_config()))
        server = None
        fd = None
        with patch("ecosystem.opencode_launch.derive_capacity", return_value=effective_record()):
            try:
                env, fd, record = prepare_environment(COMMAND, env, ROOT)
                server, url = observable.start_server(COMMAND[0], root, env, root / "server.log")
                verify_server_capacity(url, root, record, "http://127.0.0.1:13305/v1",
                                       binary=COMMAND[0], root=ROOT)
                import urllib.request
                with urllib.request.urlopen(url + "/session?directory=" + str(root), timeout=5) as reply:
                    assert json.load(reply) == []
            finally:
                if server is not None:
                    observable.stop_child(server)
                if fd is not None:
                    os.close(fd)


def test_real_client_sends_the_configured_output_allowance_to_inert_backend():
    """Request capture uses synthetic SSE, never Lemonade or model computation."""
    requests = []
    class Capture(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for delta, finish in [({"role": "assistant", "content": "probe"}, None), ({}, "stop")]:
                chunk = {"id": "chatcmpl_probe", "object": "chat.completion.chunk", "created": 0,
                         "model": "model-a", "choices": [{"index": 0, "delta": delta,
                                                         "finish_reason": finish}]}
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

    backend = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Capture)
    worker = threading.Thread(target=backend.serve_forever, daemon=True)
    worker.start()
    script = ROOT / "scripts/opencode_observable.py"
    sys.path.insert(0, str(script.parent))
    spec = importlib.util.spec_from_file_location("observable_wire_test", script)
    observable = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(observable)
    try:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = {key: value for key, value in os.environ.items() if not key.startswith("OPENCODE_")}
            env.update(XDG_CONFIG_HOME=str(root / "config"), XDG_DATA_HOME=str(root / "data"),
                       XDG_CACHE_HOME=str(root / "cache"), XDG_STATE_HOME=str(root / "state"),
                       OPENCODE_CONFIG_CONTENT=json.dumps(_stale_config()))
            base = f"http://127.0.0.1:{backend.server_port}"
            server = fd = None
            with patch("ecosystem.opencode_launch.derive_capacity", return_value=effective_record(output_reserve=128)), \
                    patch("ecosystem.opencode_launch.models.BASE", base):
                try:
                    env, fd, record = prepare_environment(COMMAND, env, ROOT)
                    server, url = observable.start_server(COMMAND[0], root, env, root / "server.log")
                    verify_server_capacity(url, root, record, base + "/v1", binary=COMMAND[0], root=ROOT)
                    client_env = dict(env)
                    client_env.pop("OPENCODE_CONFIG", None)
                    client_env.pop("OPENCODE_CONFIG_CONTENT", None)
                    result = subprocess.run([*COMMAND, "--pure", "--attach", url, "--dir", str(root),
                                             "--format", "json", "Reply with probe."],
                                            env=client_env, capture_output=True, text=True, timeout=30)
                    assert result.returncode == 0, result.stderr
                    assert requests, "client sent no inference request to the inert backend"
                    assert all(body.get("max_tokens") == 128 for body in requests)
                finally:
                    if server is not None:
                        observable.stop_child(server)
                    if fd is not None:
                        os.close(fd)
    finally:
        backend.shutdown()
        backend.server_close()
        worker.join(timeout=5)


def load_tests(_loader, _tests, _pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(value)
        for name, value in globals().items() if name.startswith("test_") and callable(value))
