import json
import os
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from ecosystem import inference_proxy
from ecosystem.inference_proxy import (
    _backend_json, _backend_process_identity, backend_snapshot, observe_backend_idle,
)


MODEL_ID = "Qwen3.8-27B-GGUF"
GATEWAY_BASE = "http://127.0.0.1:8001/v1"
BACKEND_BASE = "http://127.0.0.1:8002/v1"
BOOT_ID = "3f6c2d4e-9a1b-4c5d-8e7f-0123456789ab"
MODEL_PATH = "/models/Qwen3.8-27B-GGUF.gguf"
PID = 62259
START_TICKS = 123456

PROPS = {"total_slots": 1, "model_path": MODEL_PATH, "owner": "private-owner"}

IDENTITY = {
    "gateway_base": GATEWAY_BASE,
    "backend_base": BACKEND_BASE,
    "model_id": MODEL_ID,
    "pid": PID,
    "process_start_ticks": START_TICKS,
    "boot_id": BOOT_ID,
    "model_path": MODEL_PATH,
    "total_slots": 1,
}


def process_identity(**changes):
    identity = {"pid": PID, "process_start_ticks": START_TICKS, "boot_id": BOOT_ID}
    identity.update(changes)
    return identity


def health_entry(busy, **changes):
    entry = {
        "model_name": MODEL_ID,
        "backend_url": BACKEND_BASE,
        "pid": PID,
        "backend_alive": True,
        "loaded": True,
        "is_busy": busy,
    }
    entry.update(changes)
    return entry


def health_payload(busy=False, **changes):
    return {"all_models_loaded": [health_entry(busy, **changes)]}


def routes(busy=False, health=None, props=PROPS, slots=None, unavailable=()):
    value = {
        (GATEWAY_BASE, "/api/v1/health"):
            health if health is not None else health_payload(busy),
        (BACKEND_BASE, "/props"): props,
        (BACKEND_BASE, "/slots"):
            [{"id": 0, "is_processing": False, "prompt": "private-slot-data"}]
            if slots is None else slots,
    }
    for key in unavailable:
        del value[key]
    return value


def run_with_fakes(under_test, *arguments, json_routes=None, identities=None):
    json_routes = routes() if json_routes is None else json_routes
    remaining = list(identities) if identities is not None else [process_identity()]
    json_calls, identity_calls = [], []

    def fake_json(base, path):
        json_calls.append((base, path))
        payload = json_routes.get((base, path))
        if isinstance(payload, BaseException):
            raise payload
        if payload is None:
            raise ConnectionError("backend unavailable")
        return payload

    def fake_identity(pid):
        identity_calls.append(pid)
        if len(remaining) > 1:
            return remaining.pop(0)
        return remaining[0] if remaining else None

    with patch.object(inference_proxy, "_backend_json", fake_json), \
            patch.object(inference_proxy, "_backend_process_identity", fake_identity):
        result = under_test(*arguments)
    return result, json_calls, identity_calls


def test_snapshot_captures_stable_identity():
    result, json_calls, identity_calls = run_with_fakes(
        backend_snapshot, GATEWAY_BASE, MODEL_ID)
    assert result == {"identity": IDENTITY, "busy": False}
    assert json_calls == [(GATEWAY_BASE, "/api/v1/health"), (BACKEND_BASE, "/props")]
    assert identity_calls == [PID, PID]


def test_snapshot_allows_busy_backend():
    result, _calls, _pids = run_with_fakes(
        backend_snapshot, GATEWAY_BASE, MODEL_ID, json_routes=routes(busy=True))
    assert result is not None
    assert result["busy"] is True
    assert result["identity"] == IDENTITY


def test_idle_observation_refuses_busy_backend():
    result, json_calls, _pids = run_with_fakes(
        observe_backend_idle, dict(IDENTITY), json_routes=routes(busy=True))
    assert result is None
    assert json_calls == [(GATEWAY_BASE, "/api/v1/health"), (BACKEND_BASE, "/props")]


def test_idle_observation_succeeds_when_all_slots_idle():
    recorded = dict(IDENTITY)
    result, _calls, _pids = run_with_fakes(observe_backend_idle, recorded)
    assert result == {"identity": IDENTITY, "all_slots_idle": True,
                      "slots": [{"id": 0, "is_processing": False}]}
    recorded["pid"] = 1
    assert result["identity"]["pid"] == PID


def test_idle_observation_refuses_identity_change_before_slots():
    result, json_calls, _pids = run_with_fakes(
        observe_backend_idle, dict(IDENTITY),
        identities=[process_identity(process_start_ticks=999), process_identity()])
    assert result is None
    assert json_calls == [(GATEWAY_BASE, "/api/v1/health"), (BACKEND_BASE, "/props")]


def test_idle_observation_refuses_identity_change_after_slots():
    result, _calls, identity_calls = run_with_fakes(
        observe_backend_idle, dict(IDENTITY),
        identities=[process_identity(), process_identity(),
                    process_identity(process_start_ticks=999)])
    assert result is None
    assert identity_calls == [PID, PID, PID, PID]


def test_idle_observation_refuses_missing_or_non_list_slots():
    missing, _calls, _pids = run_with_fakes(
        observe_backend_idle, dict(IDENTITY),
        json_routes=routes(unavailable=[(BACKEND_BASE, "/slots")]))
    assert missing is None
    non_list, _calls, _pids = run_with_fakes(
        observe_backend_idle, dict(IDENTITY), json_routes=routes(slots={"slots": []}))
    assert non_list is None


def test_idle_observation_refuses_partial_slots():
    props = {"total_slots": 2, "model_path": MODEL_PATH}
    identity = {**IDENTITY, "total_slots": 2}
    partial, _calls, _pids = run_with_fakes(
        observe_backend_idle, identity,
        json_routes=routes(props=props, slots=[{"id": 0, "is_processing": False}]))
    assert partial is None
    empty, _calls, _pids = run_with_fakes(
        observe_backend_idle, identity, json_routes=routes(props=props, slots=[]))
    assert empty is None


def test_idle_observation_refuses_duplicate_slot_ids():
    props = {"total_slots": 2, "model_path": MODEL_PATH}
    identity = {**IDENTITY, "total_slots": 2}
    result, _calls, _pids = run_with_fakes(
        observe_backend_idle, identity,
        json_routes=routes(props=props, slots=[
            {"id": 0, "is_processing": False},
            {"id": 0, "is_processing": False},
        ]))
    assert result is None


def test_idle_observation_refuses_unknown_or_busy_slot_fields():
    unknown = [{"id": 0, "prompt": "private"}]
    busy_slot = [{"id": 0, "is_processing": True}]
    negative = [{"id": -1, "is_processing": False}]
    boolean_id = [{"id": False, "is_processing": False}]
    for slots in (unknown, busy_slot, negative, boolean_id):
        result, _calls, _pids = run_with_fakes(
            observe_backend_idle, dict(IDENTITY), json_routes=routes(slots=slots))
        assert result is None


def test_idle_observation_never_returns_private_slot_fields():
    slots = [{"id": 0, "is_processing": False, "prompt": "private prompt",
              "session": "private-session"}]
    result, _calls, _pids = run_with_fakes(
        observe_backend_idle, dict(IDENTITY), json_routes=routes(slots=slots))
    assert result is not None
    assert result["slots"] == [{"id": 0, "is_processing": False}]
    assert "private" not in json.dumps(result)


def test_idle_observation_requires_exact_recorded_identity():
    padded = {**IDENTITY, "note": "extra"}
    result, _calls, _pids = run_with_fakes(observe_backend_idle, padded)
    assert result is None


def test_idle_observation_refuses_malformed_identity_record():
    assert observe_backend_idle(None) is None
    assert observe_backend_idle({"gateway_base": GATEWAY_BASE}) is None


def test_snapshot_refuses_process_identity_change_during_capture():
    result, _calls, _pids = run_with_fakes(
        backend_snapshot, GATEWAY_BASE, MODEL_ID,
        identities=[process_identity(), process_identity(boot_id="rebooted")])
    assert result is None


def test_snapshot_refuses_missing_or_ambiguous_model_metadata():
    missing = {"all_models_loaded": [health_entry(False, model_name="other-model")]}
    ambiguous = {"all_models_loaded": [health_entry(False), health_entry(False)]}
    no_key = {"healthy": True}
    for health in (missing, ambiguous, no_key):
        result, _calls, _pids = run_with_fakes(
            backend_snapshot, GATEWAY_BASE, MODEL_ID, json_routes=routes(health=health))
        assert result is None


def test_snapshot_refuses_invalid_health_fields():
    invalid = (
        health_entry(False, loaded=False),
        health_entry(False, backend_alive=False),
        health_entry(False, is_busy="yes"),
        health_entry(False, pid=0),
        health_entry(False, pid=True),
        health_entry(False, backend_url="http://10.1.1.1:8002/v1"),
        health_entry(False, backend_url=BACKEND_BASE + "/chat"),
    )
    for entry in invalid:
        result, _calls, _pids = run_with_fakes(
            backend_snapshot, GATEWAY_BASE, MODEL_ID,
            json_routes=routes(health={"all_models_loaded": [entry]}))
        assert result is None


def test_snapshot_refuses_invalid_props():
    invalid = (
        {"total_slots": 0, "model_path": MODEL_PATH},
        {"total_slots": "1", "model_path": MODEL_PATH},
        {"total_slots": 1, "model_path": ""},
        {"total_slots": 1},
    )
    for props in invalid:
        result, _calls, _pids = run_with_fakes(
            backend_snapshot, GATEWAY_BASE, MODEL_ID, json_routes=routes(props=props))
        assert result is None


def test_snapshot_refuses_unavailable_gateway():
    result, _calls, _pids = run_with_fakes(
        backend_snapshot, "http://10.9.8.7:8001/v1", MODEL_ID)
    assert result is None


def make_fake_connection(body, status=200):
    events = []
    response = types.SimpleNamespace(
        status=status, read=lambda maximum: body[:maximum])
    connection = types.SimpleNamespace(
        request=lambda method, target: events.append((method, target)),
        getresponse=lambda: response,
        close=lambda: events.append("close"))
    return connection, events


def expect_value_error(function):
    try:
        function()
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_backend_json_uses_bounded_get_and_closes_connection():
    connection, events = make_fake_connection(b'{"ok": true}')
    created = []

    def factory(host, port, timeout=None):
        created.append((host, port, timeout))
        return connection

    with patch("ecosystem.inference_proxy.http.client.HTTPConnection",
               side_effect=factory):
        payload = _backend_json(BACKEND_BASE, "/api/v1/health")
    assert payload == {"ok": True}
    assert created == [("127.0.0.1", 8002, 1)]
    assert events == [("GET", "/api/v1/health"), "close"]


def test_backend_json_rejects_non_200_status_and_closes():
    connection, events = make_fake_connection(b"", status=302)
    with patch("ecosystem.inference_proxy.http.client.HTTPConnection",
               return_value=connection):
        expect_value_error(lambda: _backend_json(BACKEND_BASE, "/api/v1/health"))
    assert events == [("GET", "/api/v1/health"), "close"]


def test_backend_json_enforces_bounded_read():
    exact = b'{"pad":"' + b"a" * (1048576 - 12) + b'"}'
    connection, events = make_fake_connection(exact)
    with patch("ecosystem.inference_proxy.http.client.HTTPConnection",
               return_value=connection):
        payload = _backend_json(BACKEND_BASE, "/slots")
    assert len(payload["pad"]) == 1048576 - 12
    assert events == [("GET", "/slots"), "close"]
    connection, events = make_fake_connection(b"x" * 1048577)
    with patch("ecosystem.inference_proxy.http.client.HTTPConnection",
               return_value=connection):
        expect_value_error(lambda: _backend_json(BACKEND_BASE, "/slots"))
    assert events == [("GET", "/slots"), "close"]


def test_backend_json_rejects_invalid_json():
    connection, _events = make_fake_connection(b"not json")
    with patch("ecosystem.inference_proxy.http.client.HTTPConnection",
               return_value=connection):
        expect_value_error(lambda: _backend_json(BACKEND_BASE, "/slots"))


def test_backend_json_refuses_non_loopback_base_without_connecting():
    with patch("ecosystem.inference_proxy.http.client.HTTPConnection") as factory:
        expect_value_error(lambda: _backend_json("http://10.9.8.7:8002/v1", "/slots"))
    factory.assert_not_called()


def test_backend_process_identity_reads_live_process():
    identity = _backend_process_identity(os.getpid())
    assert identity is not None
    assert identity["pid"] == os.getpid()
    assert type(identity["process_start_ticks"]) is int
    assert identity["process_start_ticks"] > 0
    assert type(identity["boot_id"]) is str and identity["boot_id"]


def test_backend_process_identity_rejects_invalid_or_absent_pids():
    pid_max = int(Path("/proc/sys/kernel/pid_max").read_text().strip())
    for pid in (0, -3, True, "7", pid_max + 1):
        assert _backend_process_identity(pid) is None


def test_backend_process_identity_rejects_zombie_and_dead_states():
    def fake_read_text(self, encoding=None):
        if "boot_id" in str(self):
            return "0123456789abcdef0123456789abcdef\n"
        return "7 (fake) " + " ".join(suffix)

    for state in ("Z", "X"):
        suffix = [state] + ["0"] * 18 + ["42"]
        with patch.object(Path, "read_text", new=fake_read_text):
            assert _backend_process_identity(7) is None, state


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(unittest.FunctionTestCase(function) for function in functions)
