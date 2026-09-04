import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ecosystem import cli, resource_control, time_policy
from ecosystem.models import (
    _routing_prompt,
    admission,
    admitted_or_substitute,
    context_options,
    required_labels,
    role_compatible,
    route,
)


def unexpected_external_call(*arguments, **keywords):
    raise AssertionError(f"unexpected external call: {arguments!r} {keywords!r}")


def with_root(function):
    def run():
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(cli, "ROOT", Path(temporary)), \
                patch("ecosystem.resource_control._user_systemctl",
                      side_effect=unexpected_external_call), \
                patch("ecosystem.resource_control._lemonade_request",
                      side_effect=unexpected_external_call):
            cli.initialize()
            function(Path(temporary))
    run.__name__ = function.__name__
    return run


EMERGENCY_PHASES = (
    "recorded",
    "clients_stopped",
    "models_unloaded",
    "model_loaded",
    "survivor_ready",
    "active",
)


def healthy_snapshot(oom_kills=0):
    return {
        "at": "now",
        "boot_id": "boot",
        "oom_kills": oom_kills,
        "memory_available_gb": 80.0,
        "swap_used_gb": 0.0,
        "memory_full_avg10": 0.0,
        "gtt_used_gb": 20.0,
    }


def pressure_snapshot(oom_kills=0):
    return {
        **healthy_snapshot(oom_kills),
        "gtt_used_gb": 58.0,
    }


def critical_psi_snapshot(oom_kills=0):
    return {
        **healthy_snapshot(oom_kills),
        "memory_full_avg10": 2.0,
    }


def normal_resource_state():
    return {
        "version": 1,
        "mode": "normal",
        "boot_id": "boot",
        "last_oom_kills": 0,
    }


def initialize_survivor_context(root):
    (root / "roles").mkdir(parents=True, exist_ok=True)
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "roles/_base.md").write_text("Base context.\n", encoding="utf-8")
    (root / "roles/sole_survivor.md").write_text("Survivor context.\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("Repository instructions.\n", encoding="utf-8")
    (root / "config/workspaces.json").write_text("{}\n", encoding="utf-8")


def emergency_health(status="ready"):
    return {
        "all_models_loaded": [{
            "model_name": "Qwen3.5-4B-GGUF",
            "loaded": True,
            "backend_alive": True,
            "status": status,
        }],
    }


def read_job(root, identifier):
    return json.loads((root / "state/jobs" / f"{identifier}.json").read_text(encoding="utf-8"))


def transition_state(phase="model_loaded", sole_survivor_job=None):
    return {
        "version": 1,
        "mode": "emergency",
        "boot_id": "boot",
        "last_oom_kills": 0,
        "incident_id": "incident-test",
        "incident_path": "state/resource-incidents/incident-test.json",
        "emergency_reason": "test emergency",
        "emergency_phase": phase,
        "sole_survivor_job": sole_survivor_job,
    }


def systemctl_units(calls):
    return [argument for call in calls for argument in call if argument.endswith(".service")]


def in_memory_systemctl(calls=None, failed_action=None, ambiguous_unit=None,
                        missing_process_unit=None, start_pid_sequences=None):
    recorded = calls if calls is not None else []
    states = {
        "agent-ecosystem.service": {
            "active_state": "active",
            "control_group": "/user.slice/agent-ecosystem.service",
            "main_pid": 4101,
        },
        "agent-control-worker.service": {
            "active_state": "active",
            "control_group": "/user.slice/agent-control-worker.service",
            "main_pid": 4102,
        },
    }
    pid_sequences = {
        unit: list(values) for unit, values in (start_pid_sequences or {}).items()
    }

    def invoke(*arguments):
        recorded.append(arguments)
        action = arguments[0]
        if action == failed_action:
            return {"ok": False, "error": f"injected {action} failure"}
        if action in {"start", "stop"}:
            for unit in systemctl_units([arguments]):
                states[unit] = ({
                    "active_state": "active",
                    "control_group": f"/user.slice/{unit}",
                    "main_pid": states[unit]["main_pid"] or (4101 if "ecosystem" in unit else 4102),
                } if action == "start" else {
                    "active_state": "inactive",
                    "control_group": "",
                    "main_pid": 0,
                })
            return {"ok": True, "returncode": 0, "stdout": ""}
        if action == "show":
            unit = arguments[1]
            state = states[unit].copy()
            if unit == ambiguous_unit:
                state = ({"active_state": "inactive", "control_group": "", "main_pid": 0}
                         if state["active_state"] == "active" else
                         {"active_state": "active", "control_group": f"/user.slice/{unit}",
                          "main_pid": 4101 if "ecosystem" in unit else 4102})
            if unit == missing_process_unit:
                state["main_pid"] = 0
            if pid_sequences.get(unit):
                state["main_pid"] = pid_sequences[unit].pop(0)
            main_pid = (f"MainPID={state['main_pid']}\n"
                        if "--property=MainPID" in arguments else "")
            return {
                "ok": True,
                "returncode": 0,
                "stdout": (
                    f"ActiveState={state['active_state']}\n"
                    f"ControlGroup={state['control_group']}\n"
                    f"{main_pid}"
                ),
            }
        raise AssertionError(f"unexpected systemctl action: {arguments!r}")

    return invoke


def in_memory_lemonade(calls=None, initially_loaded=True):
    recorded = calls if calls is not None else []
    runtime = {"loaded": initially_loaded, "health_reads": 0}

    def request(path, payload=None, method=None, timeout=None):
        recorded.append({
            "path": path,
            "payload": payload,
            "method": method,
            "timeout": timeout,
        })
        if path == "/v1/health":
            runtime["health_reads"] += 1
            return emergency_health() if runtime["loaded"] else {"all_models_loaded": []}
        if path == "/v1/unload":
            runtime["loaded"] = False
            return {"unloaded": True}
        if path == "/v1/load":
            runtime["loaded"] = True
            return {"loaded": True}
        raise AssertionError(f"unexpected Lemonade path: {path}")

    return request


def test_oversized_vllm_is_refused_before_load():
    inventory = {
        "memory_available_gb": 11.5,
        "memory": {"gtt_used_gb": 80.5},
        "models": [{
            "id": "Qwen3.6-27B-FP16-vLLM",
            "recipe": "vllm",
            "size_gb": 51.8,
            "loaded": False,
            "labels": ["reasoning", "tool-calling"],
        }],
    }
    allowed, reason = admission("Qwen3.6-27B-FP16-vLLM", inventory)
    assert not allowed
    assert "only 11.5 GiB is available" in reason


def test_nonresident_model_substitutes_only_a_compatible_resident_model():
    inventory = {
        "memory_available_gb": 20.0,
        "memory": {"gtt_used_gb": 44.0},
        "models": [
            {"id": "desired", "recipe": "llamacpp", "size_gb": 30.0,
             "loaded": False, "labels": ["coding", "tool-calling"]},
            {"id": "chat-only", "recipe": "llamacpp", "size_gb": 4.0,
             "loaded": True, "labels": ["chat"]},
            {"id": "resident-coder", "recipe": "llamacpp", "size_gb": 17.0,
             "loaded": True, "labels": ["coding", "tool-calling"]},
        ],
    }
    selected, reason = admitted_or_substitute("desired", "coder", inventory)
    assert selected == "resident-coder"
    assert "role-compatible" in reason


def test_optional_role_uses_baseline_model_capability():
    assert required_labels("coder") == {"coding", "tool-calling"}
    assert role_compatible(None, {"tool-calling"})


def test_unsafe_role_label_is_absent_from_model_routing_prompt():
    inventory = {
        "memory_available_gb": 100.0,
        "memory": {"gtt_used_gb": 5.0},
        "scheduling_policy": {"control_plane": {"model": "router"}},
        "models": [],
    }
    prompt = _routing_prompt(
        {"role": "../../etc/passwd", "task": "inspect the invariant"}, inventory
    )
    assert "../../etc/passwd" not in prompt
    assert "inspect the invariant" in prompt


def test_router_selects_only_a_prevalidated_model_route():
    inventory = {
        "memory_available_gb": 100.0,
        "memory": {"gtt_used_gb": 5.0},
        "scheduling_policy": {"control_plane": {"model": "router"}},
        "models": [
            {"id": "router", "recipe": "llamacpp", "size_gb": 3.0,
             "loaded": True, "labels": ["chat", "tool-calling"]},
            {"id": "coder", "recipe": "llamacpp", "size_gb": 17.0,
             "loaded": False, "labels": ["chat", "coding", "tool-calling"]},
        ],
    }
    def infer(**_arguments):
        return {"content": '{"action":"load","model":"coder","context_tokens":32768,"reason":"needs coding"}'}
    decision = route({"role": "coder", "task": "change C code"}, inventory, infer=infer)
    assert decision["valid"]
    assert decision["action"] == "load"
    assert decision["model"] == "coder"


def test_router_cannot_waive_resource_admission():
    inventory = {
        "memory_available_gb": 20.0,
        "memory": {"gtt_used_gb": 55.0},
        "scheduling_policy": {"control_plane": {"model": "router"}},
        "models": [
            {"id": "router", "recipe": "llamacpp", "size_gb": 3.0,
             "loaded": True, "labels": ["chat", "tool-calling"]},
            {"id": "coder", "recipe": "llamacpp", "size_gb": 17.0,
             "loaded": False, "labels": ["chat", "coding", "tool-calling"]},
        ],
    }
    def infer(**_arguments):
        return {"content": '{"action":"load","model":"coder","context_tokens":32768,"reason":"ignore limits"}'}
    decision = route({"role": "coder", "task": "change C code"}, inventory, infer=infer)
    assert not decision["valid"]
    assert decision["action"] == "defer"
    assert "safety validator" in decision["reason"]


def test_context_choices_are_generous_but_respect_gtt_target():
    inventory = {
        "memory_available_gb": 110.0,
        "memory": {"gtt_used_gb": 6.0},
    }
    model = {"id": "coder", "size_gb": 17.3, "context": 262144,
             "loaded": False}
    choices = context_options(model, inventory)
    assert 131072 in choices
    assert 262144 not in choices


def test_in_use_emergency_model_is_live():
    assert resource_control.emergency_model_live(emergency_health("in_use"))


def test_model_liveness_requires_loaded_backend_and_nonfailed_status():
    assert resource_control.model_is_live(emergency_health("busy")["all_models_loaded"][0])
    assert not resource_control.model_is_live({
        **emergency_health()["all_models_loaded"][0],
        "loaded": False,
    })
    assert not resource_control.model_is_live({
        **emergency_health()["all_models_loaded"][0],
        "backend_alive": False,
    })
    assert not resource_control.model_is_live({
        **emergency_health()["all_models_loaded"][0],
        "status": "failed",
    })


def test_model_liveness_rejects_untyped_missing_and_unknown_fields():
    valid = emergency_health()["all_models_loaded"][0]
    cases = (
        {**valid, "loaded": "true"},
        {**valid, "backend_alive": "true"},
        {key: value for key, value in valid.items() if key != "status"},
        {**valid, "status": "warming"},
    )
    for item in cases:
        assert not resource_control.model_is_live(item)


@with_root
def test_emergency_model_context_is_usable_per_parallel_request(_root):
    calls = []
    with patch("ecosystem.resource_control._lemonade_request",
               side_effect=in_memory_lemonade(calls, initially_loaded=False)):
        result = resource_control.load_emergency_model()

    emergency = resource_control.policy()["emergency"]
    load = next(call for call in calls if call["path"] == "/v1/load")
    total_context = load["payload"]["ctx_size"]
    parallel_requests = emergency["parallel_requests"]
    assert result["ok"] is True
    assert total_context == emergency["chat_context_tokens"] * parallel_requests
    assert total_context // parallel_requests == emergency["chat_context_tokens"]
    assert 25523 < total_context // parallel_requests


@with_root
def test_model_loaded_phase_rejects_untyped_or_unknown_model_health(root):
    state = transition_state(phase="models_unloaded")
    cli.atomic_json(root / state["incident_path"], {
        "version": 1,
        "id": state["incident_id"],
    })
    valid = emergency_health()["all_models_loaded"][0]
    for item in (
            {**valid, "loaded": "false"},
            {**valid, "backend_alive": "false"},
            {key: value for key, value in valid.items() if key != "status"},
            {**valid, "status": "warming"}):
        state["emergency_phase"] = "models_unloaded"
        state.pop("emergency_error", None)
        health = {"all_models_loaded": [item]}
        with patch("ecosystem.resource_control.lemonade_health", return_value=health), \
                patch("ecosystem.resource_control.load_emergency_model",
                      return_value={"ok": True, "health": health}), \
                patch("ecosystem.resource_control._prepare_survivor",
                      side_effect=unexpected_external_call):
            result = resource_control.advance_emergency(
                state, healthy_snapshot(), "strict model health"
            )
        assert result["emergency_phase"] == "models_unloaded"
        assert result["emergency_model_ready"] is False


@with_root
def test_emergency_dispatch_authority_comes_from_exact_job_identity(root):
    resource_control.save_state({
        "version": 1,
        "mode": "emergency",
        "sole_survivor_job": "task-survivor",
    })
    survivor = {"id": "task-survivor", "role": None}
    impostor = {"id": "task-other", "role": "sole_survivor"}
    ordinary = {"id": "task-worker", "role": "worker"}
    assert resource_control.job_admitted_in_current_mode(survivor)
    assert not resource_control.job_admitted_in_current_mode(impostor)
    assert not resource_control.job_admitted_in_current_mode(ordinary)
    assert json.loads((root / "state/resource-control.json").read_text())["mode"] == "emergency"


@with_root
def test_chatbot_uses_emergency_model_while_dispatch_is_latched(_root):
    resource_control.save_state({"version": 1, "mode": "emergency"})
    assert resource_control.active_chat_model("Qwen3.8-27B-GGUF") == "Qwen3.5-4B-GGUF"


@with_root
def test_one_non_oom_critical_sample_does_not_enter_emergency(_root):
    state = normal_resource_state()
    current = critical_psi_snapshot(oom_kills=state["last_oom_kills"])
    with patch("ecosystem.resource_control.resource_snapshot", return_value=current), \
            patch("ecosystem.resource_control.load_state", return_value=state), \
            patch("ecosystem.resource_control.time.monotonic", return_value=100.0), \
            patch("ecosystem.resource_control._user_systemctl",
                  side_effect=unexpected_external_call), \
            patch("ecosystem.resource_control._lemonade_request",
                  side_effect=unexpected_external_call), \
            patch("ecosystem.resource_control.enter_emergency",
                  return_value={"mode": "emergency"}) as enter, \
            patch("ecosystem.resource_control.advance_emergency",
                  return_value={"mode": "emergency"}, create=True) as advance:
        result = resource_control.tick()
    assert result["mode"] == "normal"
    assert result["threshold_candidate"] == "emergency"
    assert enter.call_count == 0
    assert advance.call_count == 0


@with_root
def test_non_oom_thresholds_use_monotonic_confirmation_windows(_root):
    emergency_state = normal_resource_state()
    emergency_snapshot = critical_psi_snapshot()
    with patch("ecosystem.resource_control.resource_snapshot", return_value=emergency_snapshot), \
            patch("ecosystem.resource_control.load_state", return_value=emergency_state), \
            patch("ecosystem.resource_control._user_systemctl",
                  side_effect=unexpected_external_call), \
            patch("ecosystem.resource_control._lemonade_request",
                  side_effect=unexpected_external_call), \
            patch("ecosystem.resource_control.enter_emergency",
                  return_value={"mode": "emergency"}) as enter, \
            patch("ecosystem.resource_control.advance_emergency",
                  return_value={"mode": "emergency"}, create=True) as advance:
        with patch("ecosystem.resource_control.time.monotonic", return_value=100.0):
            assert resource_control.tick()["mode"] == "normal"
        with patch("ecosystem.resource_control.time.monotonic", return_value=109.999):
            assert resource_control.tick()["mode"] == "normal"
        with patch("ecosystem.resource_control.time.monotonic", return_value=110.0):
            assert resource_control.tick()["mode"] == "emergency"
    assert enter.call_count + advance.call_count == 1

    pressure_state = normal_resource_state()
    current = pressure_snapshot()
    with patch("ecosystem.resource_control.resource_snapshot", return_value=current), \
            patch("ecosystem.resource_control.load_state", return_value=pressure_state), \
            patch("ecosystem.resource_control._user_systemctl",
                  side_effect=unexpected_external_call), \
            patch("ecosystem.resource_control._lemonade_request",
                  side_effect=unexpected_external_call), \
            patch("ecosystem.resource_control.enter_pressure",
                  return_value={"mode": "pressure"}) as enter_pressure:
        with patch("ecosystem.resource_control.time.monotonic", return_value=200.0):
            assert resource_control.tick()["mode"] == "normal"
        with patch("ecosystem.resource_control.time.monotonic", return_value=205.0):
            assert resource_control.tick()["mode"] == "pressure"
    assert enter_pressure.call_count == 1


@with_root
def test_healthy_pressure_release_uses_central_monotonic_duration(_root):
    state = {
        **normal_resource_state(),
        "mode": "pressure",
        "pressure_interrupted_jobs": [],
    }
    central_policy = {
        "resource": {
            "poll_seconds": 0.75,
            "pressure_confirmation_seconds": 5.0,
            "emergency_confirmation_seconds": 10.0,
            "healthy_release_seconds": 2.0,
        },
        "lifecycle": {"reconciliation_deadline_seconds": 19.0},
    }
    with patch("ecosystem.resource_control.resource_snapshot", return_value=healthy_snapshot()), \
            patch("ecosystem.resource_control.load_state", return_value=state), \
            patch.object(time_policy, "load", return_value=central_policy), \
            patch("ecosystem.resource_control._user_systemctl",
                  side_effect=in_memory_systemctl()):
        with patch("ecosystem.resource_control.time.monotonic", return_value=300.0):
            assert resource_control.tick()["mode"] == "pressure"
        with patch("ecosystem.resource_control.time.monotonic", return_value=301.999):
            assert resource_control.tick()["mode"] == "pressure"
        with patch("ecosystem.resource_control.time.monotonic", return_value=302.0):
            assert resource_control.tick()["mode"] == "normal"


@with_root
def test_resource_guard_poll_uses_central_duration(_root):
    central_policy = {
        "resource": {
            "poll_seconds": 0.75,
            "pressure_confirmation_seconds": 5.0,
            "emergency_confirmation_seconds": 10.0,
            "healthy_release_seconds": 60.0,
        },
    }
    sleeps = []

    def stop_after_one_sleep(seconds):
        sleeps.append(seconds)
        raise RuntimeError("stop test guard")

    with patch.object(time_policy, "load", return_value=central_policy), \
            patch("ecosystem.resource_control.tick"), \
            patch("ecosystem.resource_control.time.sleep", side_effect=stop_after_one_sleep):
        with unittest.TestCase().assertRaisesRegex(RuntimeError, "stop test guard"):
            resource_control.run_guard()
    assert sleeps == [0.75]


def test_systemctl_boundary_reports_nonzero_and_timeout():
    central_policy = {"lifecycle": {"service_stop_deadline_seconds": 7.0}}
    failed = subprocess.CompletedProcess(
        ["systemctl", "--user", "stop", "agent-ecosystem.service"], 1,
        stdout="", stderr="failed",
    )
    with patch.object(time_policy, "load", return_value=central_policy), \
            patch("ecosystem.resource_control.subprocess.run", return_value=failed) as run:
        result = resource_control._user_systemctl("stop", "agent-ecosystem.service")
    assert result["ok"] is False
    assert "status 1" in result["error"]
    assert run.call_args.kwargs["timeout"] == 7.0

    timeout = subprocess.TimeoutExpired(["systemctl", "--user", "stop"], 7.0)
    with patch.object(time_policy, "load", return_value=central_policy), \
            patch("ecosystem.resource_control.subprocess.run", side_effect=timeout):
        result = resource_control._user_systemctl("stop", "agent-ecosystem.service")
    assert result["ok"] is False
    assert "timed out" in result["error"]


def test_resource_effect_adapters_use_central_deadlines_and_cadence():
    central_policy = {
        "inference": {
            "model_stop_deadline_seconds": 11.0,
            "model_start_deadline_seconds": 13.0,
            "health_verification_deadline_seconds": 17.0,
        },
        "lifecycle": {
            "service_stop_deadline_seconds": 7.0,
            "reconciliation_deadline_seconds": 19.0,
        },
        "resource": {"poll_seconds": 0.75},
    }
    requests = []
    sleeps = []
    current_health = {"value": emergency_health()}

    def lemonade(path, payload=None, method=None, timeout=None):
        requests.append((path, timeout))
        if path == "/v1/health":
            return current_health["value"]
        return {"ok": True}

    completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
    with patch.object(time_policy, "load", return_value=central_policy), \
            patch("ecosystem.resource_control.subprocess.run", return_value=completed), \
            patch("ecosystem.resource_control._lemonade_request", side_effect=lemonade), \
            patch("ecosystem.resource_control.time.sleep", side_effect=sleeps.append):
        resource_control._user_systemctl("stop", "agent-ecosystem.service")
        resource_control.lemonade_health()
        with patch("ecosystem.resource_control.lemonade_health",
                   side_effect=(emergency_health(), {"all_models_loaded": []})), \
                patch("ecosystem.resource_control.time.monotonic", return_value=100.0):
            assert resource_control.unload_all_models()["ok"]
        resource_control.load_emergency_model()
        current_health["value"] = {
            "all_models_loaded": [
                emergency_health()["all_models_loaded"][0],
                {"model_name": "dynamic-model", "loaded": True,
                 "backend_alive": True, "status": "ready"},
            ],
        }
        resource_control.unload_dynamic_models()

    assert ("/v1/health", 17.0) in requests
    assert ("/v1/load", 13.0) in requests
    assert requests.count(("/v1/unload", 11.0)) == 2
    assert sleeps == [0.75]


def test_unload_rejects_missing_or_failed_health_records():
    for health in ({}, {"error": "health unavailable"}):
        with patch("ecosystem.resource_control._lemonade_request", return_value={}), \
                patch("ecosystem.resource_control.lemonade_health", return_value=health), \
                patch("ecosystem.resource_control.time.monotonic", return_value=100.0):
            result = resource_control.unload_all_models()
        assert result["ok"] is False
        assert "health" in result["error"]


@with_root
def test_clients_stopped_requires_successful_actions_and_empty_cgroups(root):
    for name, systemctl in (
            ("failed_action", in_memory_systemctl(failed_action="stop")),
            ("ambiguous_cgroup", in_memory_systemctl(
                ambiguous_unit="agent-control-worker.service")),
    ):
        case_root = root / name
        with patch.object(cli, "ROOT", case_root):
            cli.initialize()
            state = transition_state(phase="recorded")
            cli.atomic_json(case_root / state["incident_path"], {
                "version": 1,
                "id": state["incident_id"],
            })
            with patch("ecosystem.resource_control.checkpoint_running_jobs",
                       return_value=[]), \
                    patch("ecosystem.resource_control._user_systemctl",
                          side_effect=systemctl), \
                    patch("ecosystem.resource_control.unload_all_models",
                          return_value={"ok": False, "error": "must not run"}) as unload:
                result = resource_control.advance_emergency(
                    state, healthy_snapshot(), "stop verification"
                )
        assert result["emergency_phase"] == "recorded"
        assert "client interruption failed" in result["emergency_error"]
        assert unload.call_count == 0


@with_root
def test_active_phase_requires_successful_start_and_observed_running_units(root):
    identifier = "task-survivor"
    for name, systemctl in (
            ("failed_action", in_memory_systemctl(failed_action="start")),
            ("ambiguous_cgroup", in_memory_systemctl(
                ambiguous_unit="agent-control-worker.service")),
    ):
        state = transition_state(phase="survivor_ready", sole_survivor_job=identifier)
        cli.atomic_json(root / "state/jobs" / f"{identifier}.json", {
            "id": identifier,
            "state": "ready",
            "source": f"resource-emergency:{state['incident_id']}",
        })
        with patch("ecosystem.resource_control.lemonade_health",
                   return_value=emergency_health()), \
                patch("ecosystem.resource_control._user_systemctl",
                      side_effect=systemctl), \
                patch("ecosystem.resource_control.time.monotonic",
                      side_effect=(100.0, 160.0)), \
                patch("ecosystem.resource_control.time.sleep",
                      side_effect=unexpected_external_call), \
                patch("ecosystem.resource_control.os.sync"):
            result = resource_control.advance_emergency(
                state, healthy_snapshot(), f"start verification {name}"
            )
        assert result["emergency_phase"] == "survivor_ready"
        assert "start failed" in result["emergency_error"]


@with_root
def test_active_phase_waits_for_each_unit_live_process(root):
    identifier = "task-survivor"
    state = transition_state(phase="survivor_ready", sole_survivor_job=identifier)
    cli.atomic_json(root / "state/jobs" / f"{identifier}.json", {
        "id": identifier,
        "state": "ready",
        "source": f"resource-emergency:{state['incident_id']}",
    })
    central_policy = {
        "lifecycle": {"reconciliation_deadline_seconds": 19.0},
        "resource": {"poll_seconds": 0.75},
    }
    sleeps = []
    systemctl = in_memory_systemctl(start_pid_sequences={
        "agent-control-worker.service": [0, 4102],
        "agent-ecosystem.service": [0, 4101],
    })
    with patch.object(time_policy, "load", return_value=central_policy), \
            patch("ecosystem.resource_control.lemonade_health",
                  return_value=emergency_health()), \
            patch("ecosystem.resource_control._user_systemctl", side_effect=systemctl), \
            patch("ecosystem.resource_control.time.monotonic", return_value=100.0), \
            patch("ecosystem.resource_control.time.sleep", side_effect=sleeps.append), \
            patch("ecosystem.resource_control.os.sync"):
        result = resource_control.advance_emergency(
            state, healthy_snapshot(), "bounded process convergence"
        )

    assert result["emergency_phase"] == "active"
    assert sleeps == [0.75]
    assert all(item["main_pid"] > 0
               for item in result["survivor_start_result"]["states"])


@with_root
def test_started_unit_wait_never_sleeps_past_reconciliation_deadline(_root):
    central_policy = {
        "lifecycle": {"reconciliation_deadline_seconds": 19.0},
        "resource": {"poll_seconds": 30.0},
    }
    sleeps = []
    with patch.object(time_policy, "load", return_value=central_policy), \
            patch("ecosystem.resource_control._user_systemctl",
                  side_effect=in_memory_systemctl(
                      missing_process_unit="agent-ecosystem.service")), \
            patch("ecosystem.resource_control.time.monotonic",
                  side_effect=(100.0, 100.0, 119.0)), \
            patch("ecosystem.resource_control.time.sleep", side_effect=sleeps.append):
        result = resource_control._start_user_units(("agent-ecosystem.service",))
    assert result["ok"] is False
    assert sleeps == [19.0]


@with_root
def test_active_tick_reobserves_required_unit_processes(root):
    identifier = "task-survivor"
    state = transition_state(phase="active", sole_survivor_job=identifier)
    cli.atomic_json(root / "state/jobs" / f"{identifier}.json", {
        "id": identifier,
        "state": "running",
        "source": f"resource-emergency:{state['incident_id']}",
    })
    with patch("ecosystem.resource_control.lemonade_health",
               return_value=emergency_health()), \
            patch("ecosystem.resource_control._user_systemctl",
                  side_effect=in_memory_systemctl(
                      missing_process_unit="agent-ecosystem.service")):
        result = resource_control.advance_emergency(
            state, healthy_snapshot(), "active liveness observation"
        )

    assert result["emergency_phase"] == "active"
    assert "live process" in result.get("emergency_error", "")
    assert {item["unit"] for item in result["active_service_result"]["states"]} == {
        "agent-control-worker.service",
        "agent-ecosystem.service",
    }


@with_root
def test_emergency_entry_creates_survivor_before_active_phase(root):
    initialize_survivor_context(root)
    state = normal_resource_state()
    saved = []
    systemctl_calls = []
    real_save_state = resource_control.save_state

    def save_and_capture(current):
        real_save_state(current)
        saved.append(json.loads(json.dumps(current)))

    with patch("ecosystem.resource_control.save_state", side_effect=save_and_capture), \
            patch("ecosystem.resource_control.lemonade_health", return_value=emergency_health()), \
            patch("ecosystem.resource_control.unload_all_models",
                  return_value={"ok": True, "health": {"all_models_loaded": []}}), \
            patch("ecosystem.resource_control.load_emergency_model",
                  return_value={"ok": True, "health": emergency_health()}), \
            patch("ecosystem.resource_control._user_systemctl",
                  side_effect=in_memory_systemctl(systemctl_calls)), \
            patch("ecosystem.resource_control.os.sync"):
        result = resource_control.advance_emergency(state, healthy_snapshot(), "test emergency")

    assert result["mode"] == "emergency"
    assert result["emergency_phase"] == "active"
    assert read_job(root, result["sole_survivor_job"])["role"] == "sole_survivor"
    distinct_phases = []
    for item in saved:
        phase = item.get("emergency_phase")
        if phase and (not distinct_phases or distinct_phases[-1] != phase):
            distinct_phases.append(phase)
    assert distinct_phases == list(EMERGENCY_PHASES)
    active = next(item for item in saved if item.get("emergency_phase") == "active")
    assert read_job(root, active["sole_survivor_job"])["state"] == "ready"
    assert "agent-telegram.service" not in systemctl_units(systemctl_calls)
    assert "agent-notifier.service" not in systemctl_units(systemctl_calls)


@with_root
def test_retry_resumes_model_loaded_phase_without_restarting_contact(root):
    initialize_survivor_context(root)
    state = transition_state()
    incident_path = root / state["incident_path"]
    cli.atomic_json(incident_path, {"version": 1, "id": state["incident_id"]})
    systemctl_calls = []
    with patch("ecosystem.resource_control.lemonade_health", return_value=emergency_health("busy")), \
            patch("ecosystem.resource_control._prepare_survivor",
                  wraps=resource_control._prepare_survivor) as prepare, \
            patch("ecosystem.resource_control._user_systemctl",
                  side_effect=in_memory_systemctl(systemctl_calls)), \
            patch("ecosystem.resource_control.os.sync"):
        result = resource_control.advance_emergency(state, healthy_snapshot(), "retry")
    assert result["sole_survivor_job"]
    assert result["emergency_phase"] == "active"
    assert prepare.call_count == 1
    assert "agent-telegram.service" not in systemctl_units(systemctl_calls)
    assert "agent-notifier.service" not in systemctl_units(systemctl_calls)


@with_root
def test_retry_repairs_legacy_emergency_without_phase_or_survivor(root):
    initialize_survivor_context(root)
    state = transition_state()
    state.pop("emergency_phase")
    state.pop("sole_survivor_job")
    incident_path = root / state["incident_path"]
    cli.atomic_json(incident_path, {"version": 1, "id": state["incident_id"]})
    runtime = {"model_loaded": False}
    systemctl_calls = []

    def health():
        return emergency_health() if runtime["model_loaded"] else {"all_models_loaded": []}

    def unload_models():
        runtime["model_loaded"] = False
        return {"ok": True, "health": health()}

    def load_model():
        runtime["model_loaded"] = True
        return {"ok": True, "health": health()}

    with patch("ecosystem.resource_control.lemonade_health", side_effect=health), \
            patch("ecosystem.resource_control.unload_all_models", side_effect=unload_models), \
            patch("ecosystem.resource_control.load_emergency_model", side_effect=load_model), \
            patch("ecosystem.resource_control._user_systemctl",
                  side_effect=in_memory_systemctl(systemctl_calls)), \
            patch("ecosystem.resource_control.os.sync"):
        result = resource_control.advance_emergency(state, healthy_snapshot(), "legacy retry")

    assert result["emergency_phase"] == "active"
    assert read_job(root, result["sole_survivor_job"])["state"] == "ready"
    assert "agent-telegram.service" not in systemctl_units(systemctl_calls)
    assert "agent-notifier.service" not in systemctl_units(systemctl_calls)


@with_root
def test_ready_survivor_can_start_run_and_remain_active(root):
    initialize_survivor_context(root)
    state = transition_state(phase="model_loaded")
    cli.atomic_json(root / state["incident_path"], {
        "version": 1,
        "id": state["incident_id"],
    })
    calls = []
    systemctl = in_memory_systemctl(calls)

    def start_survivor(*arguments):
        result = systemctl(*arguments)
        if arguments[0] == "start":
            path = root / "state/jobs" / f"{state['sole_survivor_job']}.json"
            job = json.loads(path.read_text(encoding="utf-8"))
            job["state"] = "running"
            cli.atomic_json(path, job)
        return result

    with patch("ecosystem.resource_control.lemonade_health",
               return_value=emergency_health("busy")), \
            patch("ecosystem.resource_control._user_systemctl",
                  side_effect=start_survivor), \
            patch("ecosystem.resource_control.os.sync"):
        entered = resource_control.advance_emergency(
            state, healthy_snapshot(), "executor lifecycle"
        )
        active_tick = resource_control.advance_emergency(
            entered, healthy_snapshot(), "executor lifecycle retry"
        )

    assert entered["emergency_phase"] == "active"
    assert read_job(root, entered["sole_survivor_job"])["state"] == "running"
    assert "emergency_error" not in active_tick


@with_root
def test_active_survivor_accepts_verification_and_rejects_terminal_owner(root):
    identifier = "task-survivor"
    state = transition_state(phase="active", sole_survivor_job=identifier)
    path = root / "state/jobs" / f"{identifier}.json"
    for job_state in ("awaiting_verification", "failed"):
        cli.atomic_json(path, {
            "id": identifier,
            "state": job_state,
            "source": f"resource-emergency:{state['incident_id']}",
        })
        state.pop("emergency_error", None)
        state.pop("emergency_error_at", None)
        with patch("ecosystem.resource_control.lemonade_health",
                   return_value=emergency_health()), \
                patch("ecosystem.resource_control._user_systemctl",
                      side_effect=in_memory_systemctl()):
            result = resource_control.advance_emergency(
                state, healthy_snapshot(), f"owner state {job_state}"
            )
        if job_state == "awaiting_verification":
            assert "emergency_error" not in result
        else:
            assert "survivor" in result["emergency_error"]


@with_root
def test_repeated_context_overflow_survivor_ticks_record_one_pending_escalation(root):
    identifier = "task-survivor"
    state = transition_state(phase="active", sole_survivor_job=identifier)
    output = "logs/runs/task-survivor.opencode.log"
    cli.atomic_json(root / "state/jobs" / f"{identifier}.json", {
        "id": identifier,
        "state": "failed",
        "source": f"resource-emergency:{state['incident_id']}",
        "exit_code": 1,
        "context_tokens": 32768,
        "output": output,
    })
    (root / output).parent.mkdir(parents=True, exist_ok=True)
    (root / output).write_text(
        '{"type":"error","error":{"data":{"message":'
        '"request (25523 tokens) exceeds the available context size '
        '(16384 tokens)","type":"exceed_context_size_error"}}}\n',
        encoding="utf-8",
    )
    resource_control.save_state(state)
    real_save_state = resource_control.save_state
    first_snapshot = {**healthy_snapshot(), "at": "tick-one"}
    second_snapshot = {**healthy_snapshot(), "at": "tick-two"}

    with patch("ecosystem.resource_control.resource_snapshot",
               side_effect=(first_snapshot, second_snapshot)), \
            patch("ecosystem.resource_control.lemonade_health",
                  return_value=emergency_health()), \
            patch("ecosystem.resource_control._user_systemctl",
                  side_effect=unexpected_external_call), \
            patch("ecosystem.resource_control.save_state",
                  wraps=real_save_state) as save, \
            patch("ecosystem.resource_control.cli.audit") as audit:
        first = resource_control.tick()
        first_error_at = first["emergency_error_at"]
        second = resource_control.tick()

    assert second["emergency_escalation"] == {
        "status": "required",
        "reason": "context_overflow",
        "survivor_job": identifier,
        "survivor_state": "failed",
        "exit_code": 1,
        "requested_context_tokens": 32768,
        "transcript": output,
        "error": None,
    }
    assert second["last_resources"]["at"] == "tick-two"
    assert second["emergency_error_at"] == first_error_at
    assert save.call_count == 1
    assert audit.call_count == 1
    assert audit.call_args.args == ("resource.emergency_error",)


@with_root
def test_deduplicated_survivor_error_preserves_changes_and_recovery(root):
    identifier = "task-survivor"
    state = transition_state(phase="active", sole_survivor_job=identifier)
    job_path = root / "state/jobs" / f"{identifier}.json"
    job = {
        "id": identifier,
        "state": "failed",
        "source": f"resource-emergency:{state['incident_id']}",
        "exit_code": 1,
    }
    cli.atomic_json(job_path, job)
    resource_control.save_state(state)
    changed_snapshot = {**healthy_snapshot(), "gtt_used_gb": 21.0}
    real_save_state = resource_control.save_state

    with patch("ecosystem.resource_control.resource_snapshot",
               side_effect=(healthy_snapshot(), changed_snapshot, changed_snapshot)), \
            patch("ecosystem.resource_control.lemonade_health",
                  return_value=emergency_health()), \
            patch("ecosystem.resource_control._user_systemctl",
                  side_effect=in_memory_systemctl()), \
            patch("ecosystem.resource_control.save_state",
                  wraps=real_save_state) as save, \
            patch("ecosystem.resource_control.cli.audit") as audit:
        resource_control.tick()
        changed = resource_control.tick()
        job["state"] = "running"
        cli.atomic_json(job_path, job)
        recovered = resource_control.tick()

    assert changed["last_resources"] == changed_snapshot
    assert changed["emergency_escalation"]["reason"] == "survivor_terminal"
    assert "emergency_error" not in recovered
    assert "emergency_escalation" not in recovered
    assert save.call_count == 3
    assert audit.call_count == 1


@with_root
def test_recovery_restart_failure_keeps_emergency_generation_retryable(root):
    survivor = "task-survivor"
    interrupted = "task-interrupted"
    state = transition_state(phase="active", sole_survivor_job=survivor)
    state["interrupted_jobs"] = [interrupted]
    cli.atomic_json(root / state["incident_path"], {
        "version": 1,
        "id": state["incident_id"],
    })
    cli.atomic_json(root / "state/jobs" / f"{survivor}.json", {
        "id": survivor,
        "state": "running",
        "source": f"resource-emergency:{state['incident_id']}",
    })
    cli.atomic_json(root / "state/jobs" / f"{interrupted}.json", {
        "id": interrupted,
        "state": "interrupted",
        "resume_available": True,
    })
    resource_control.save_state(state)
    central_policy = {
        "lifecycle": {"reconciliation_deadline_seconds": 19.0},
        "resource": {"poll_seconds": 0.75},
    }
    sleeps = []
    with patch.object(time_policy, "load", return_value=central_policy), \
            patch("ecosystem.resource_control.resource_snapshot",
                  return_value=healthy_snapshot()), \
            patch("ecosystem.resource_control._user_systemctl",
                  side_effect=in_memory_systemctl(
                      missing_process_unit="agent-ecosystem.service")), \
            patch("ecosystem.resource_control.time.monotonic",
                  side_effect=(100.0, 100.0, 119.0)), \
            patch("ecosystem.resource_control.time.sleep", side_effect=sleeps.append):
        failed = resource_control.request_recovery(survivor)

    persisted = resource_control.load_state()
    assert failed["ok"] is False
    assert sleeps == [0.75]
    assert persisted["mode"] == "emergency"
    assert persisted["emergency_phase"] == "active"
    assert persisted["incident_id"] == state["incident_id"]
    assert persisted["sole_survivor_job"] == survivor
    assert read_job(root, interrupted)["state"] == "interrupted"

    with patch("ecosystem.resource_control.resource_snapshot",
               return_value=healthy_snapshot()), \
            patch("ecosystem.resource_control._user_systemctl",
                  side_effect=in_memory_systemctl()):
        retried = resource_control.request_recovery(survivor)
    recovered = resource_control.load_state()
    assert retried["ok"] is True
    assert recovered["mode"] == "normal"
    assert "incident_id" not in recovered
    assert read_job(root, interrupted)["state"] == "ready"


@with_root
def test_recovery_clears_generation_before_a_second_oom(root):
    initialize_survivor_context(root)
    old_survivor = "task-old-survivor"
    state = transition_state(phase="active", sole_survivor_job=old_survivor)
    state.update(
        last_oom_kills=1,
        interrupted_jobs=[],
        emergency_model_ready=True,
        emergency_model_last_attempt="old-attempt",
        emergency_model_last_result={"ok": True},
        model_unload_result={"ok": True},
        client_stop_result={"ok": True},
        survivor_start_result={"ok": True},
        threshold_candidate="emergency",
        threshold_candidate_since_monotonic=1.0,
        pressure_interrupted_jobs=[],
        pressure_client_stop_result={"ok": True},
        pressure_client_start_result={"ok": True},
    )
    cli.atomic_json(root / state["incident_path"], {
        "version": 1,
        "id": state["incident_id"],
    })
    cli.atomic_json(root / "state/jobs" / f"{old_survivor}.json", {
        "id": old_survivor,
        "state": "ready",
        "source": f"resource-emergency:{state['incident_id']}",
    })
    resource_control.save_state(state)
    recovery_calls = []
    with patch("ecosystem.resource_control.resource_snapshot",
               return_value=healthy_snapshot(oom_kills=1)), \
            patch("ecosystem.resource_control._user_systemctl",
                  side_effect=in_memory_systemctl(recovery_calls)):
        assert resource_control.request_recovery(old_survivor)["ok"]
    recovered_state = resource_control.load_state()

    second_calls = []
    with patch("ecosystem.resource_control.resource_snapshot",
               return_value=healthy_snapshot(oom_kills=2)), \
            patch("ecosystem.resource_control._user_systemctl",
                  side_effect=in_memory_systemctl(second_calls)), \
            patch("ecosystem.resource_control._lemonade_request",
                  side_effect=in_memory_lemonade(initially_loaded=True)), \
            patch("ecosystem.resource_control.os.sync"):
        second = resource_control.tick()

    assert second["emergency_phase"] == "active"
    assert second["incident_id"] != state["incident_id"]
    assert second["sole_survivor_job"] != old_survivor
    for field in (
            "incident_id", "incident_path", "emergency_reason", "emergency_entered_at",
            "emergency_phase", "emergency_error", "emergency_error_at", "interrupted_jobs",
            "model_unload_result", "emergency_model_last_attempt",
            "emergency_model_last_result", "emergency_model_ready", "sole_survivor_job",
            "client_stop_result", "survivor_start_result", "threshold_candidate",
            "threshold_candidate_since_monotonic", "pressure_interrupted_jobs",
            "pressure_client_stop_result", "pressure_client_start_result"):
        assert field not in recovered_state
    assert (root / state["incident_path"]).exists()
    events = [
        json.loads(line)
        for path in (root / "logs/runs").glob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert any(event.get("event") == "resource.emergency_recovered"
               and event.get("incident_id") == state["incident_id"] for event in events)
    assert "agent-telegram.service" not in systemctl_units(recovery_calls + second_calls)
    assert "agent-notifier.service" not in systemctl_units(recovery_calls + second_calls)


@with_root
def test_emergency_retry_is_idempotent_after_every_persisted_phase(root):
    for injected_phase in EMERGENCY_PHASES:
        case_root = root / injected_phase
        with patch.object(cli, "ROOT", case_root):
            cli.initialize()
            initialize_survivor_context(case_root)
            state = normal_resource_state()
            runtime = {"model_loaded": False}
            systemctl_calls = []
            real_save_state = resource_control.save_state
            real_prepare_survivor = resource_control._prepare_survivor
            failure_injected = False
            systemctl = in_memory_systemctl(systemctl_calls)

            def health():
                return emergency_health() if runtime["model_loaded"] else {
                    "all_models_loaded": [],
                }

            def unload_models():
                runtime["model_loaded"] = False
                return {"ok": True, "health": health()}

            def load_model():
                runtime["model_loaded"] = True
                return {"ok": True, "health": health()}

            def save_then_fail(current):
                nonlocal failure_injected
                real_save_state(current)
                if not failure_injected and current.get("emergency_phase") == injected_phase:
                    failure_injected = True
                    raise RuntimeError(f"injected after {injected_phase}")

            with patch("ecosystem.resource_control.save_state", side_effect=save_then_fail), \
                    patch("ecosystem.resource_control.lemonade_health", side_effect=health), \
                    patch("ecosystem.resource_control.unload_all_models", side_effect=unload_models) as unload, \
                    patch("ecosystem.resource_control.load_emergency_model", side_effect=load_model) as load, \
                    patch("ecosystem.resource_control._prepare_survivor",
                          wraps=real_prepare_survivor) as prepare, \
                    patch("ecosystem.resource_control._user_systemctl",
                          side_effect=systemctl), \
                    patch("ecosystem.resource_control.os.sync"):
                with unittest.TestCase().assertRaisesRegex(RuntimeError, injected_phase):
                    resource_control.advance_emergency(
                        state, healthy_snapshot(), "failure injection"
                    )

            persisted = resource_control.load_state()
            assert persisted["emergency_phase"] == injected_phase
            incident_count = len(list((case_root / "state/resource-incidents").glob("*.json")))
            stop_count = len([call for call in systemctl_calls if call[:1] == ("stop",)])
            unload_count = unload.call_count
            load_count = load.call_count
            prepare_count = prepare.call_count
            start_count = len([call for call in systemctl_calls if call[:1] == ("start",)])

            with patch("ecosystem.resource_control.lemonade_health", side_effect=health), \
                    patch("ecosystem.resource_control.unload_all_models", side_effect=unload_models) as retry_unload, \
                    patch("ecosystem.resource_control.load_emergency_model", side_effect=load_model) as retry_load, \
                    patch("ecosystem.resource_control._prepare_survivor",
                          wraps=real_prepare_survivor) as retry_prepare, \
                    patch("ecosystem.resource_control._user_systemctl",
                          side_effect=systemctl), \
                    patch("ecosystem.resource_control.os.sync"):
                result = resource_control.advance_emergency(
                    persisted, healthy_snapshot(), "failure injection retry"
                )

            assert result["emergency_phase"] == "active"
            assert len(list((case_root / "state/resource-incidents").glob("*.json"))) == max(1, incident_count)
            if injected_phase != "recorded":
                assert len([call for call in systemctl_calls if call[:1] == ("stop",)]) == stop_count
            if EMERGENCY_PHASES.index(injected_phase) >= EMERGENCY_PHASES.index("models_unloaded"):
                assert retry_unload.call_count == 0
                assert unload.call_count == unload_count
            if EMERGENCY_PHASES.index(injected_phase) >= EMERGENCY_PHASES.index("model_loaded"):
                assert retry_load.call_count == 0
                assert load.call_count == load_count
            if EMERGENCY_PHASES.index(injected_phase) >= EMERGENCY_PHASES.index("survivor_ready"):
                assert retry_prepare.call_count == 0
                assert prepare.call_count == prepare_count
            if injected_phase == "active":
                assert len([call for call in systemctl_calls if call[:1] == ("start",)]) == start_count
            assert "agent-telegram.service" not in systemctl_units(systemctl_calls)
            assert "agent-notifier.service" not in systemctl_units(systemctl_calls)


@with_root
def test_active_emergency_records_dead_model_without_retrying_or_touching_contact(_root):
    state = transition_state(phase="active", sole_survivor_job="task-survivor")
    with patch("ecosystem.resource_control.resource_snapshot", return_value=healthy_snapshot()), \
            patch("ecosystem.resource_control.load_state", return_value=state), \
            patch("ecosystem.resource_control.lemonade_health",
                  return_value={"all_models_loaded": []}), \
            patch("ecosystem.resource_control.load_emergency_model") as load, \
            patch("ecosystem.resource_control._user_systemctl") as systemctl:
        result = resource_control.tick()
    assert result["emergency_phase"] == "active"
    assert "not live" in result["emergency_error"]
    assert load.call_count == 0
    assert systemctl.call_count == 0


@with_root
def test_one_new_oom_enters_emergency(_root):
    before = {
        "version": 1,
        "mode": "normal",
        "boot_id": "boot",
        "last_oom_kills": 4,
    }
    current = {
        "at": "now",
        "boot_id": "boot",
        "oom_kills": 5,
        "memory_available_gb": 80.0,
        "swap_used_gb": 0.0,
        "memory_full_avg10": 0.0,
        "gtt_used_gb": 20.0,
    }
    with patch("ecosystem.resource_control.resource_snapshot", return_value=current), \
            patch("ecosystem.resource_control.load_state", return_value=before), \
            patch("ecosystem.resource_control.enter_emergency", return_value={"mode": "emergency"}) as enter:
        result = resource_control.tick()
    assert result["mode"] == "emergency"
    assert enter.call_count == 1
    assert "increased from 4 to 5" in enter.call_args.args[2]


@with_root
def test_oom_before_guard_start_on_new_boot_is_not_missed(_root):
    before = {"version": 1, "mode": "normal", "boot_id": "old-boot",
              "last_oom_kills": 99}
    current = {
        "at": "now", "boot_id": "new-boot", "oom_kills": 1,
        "memory_available_gb": 80.0, "swap_used_gb": 0.0,
        "memory_full_avg10": 0.0, "gtt_used_gb": 20.0,
    }
    with patch("ecosystem.resource_control.resource_snapshot", return_value=current), \
            patch("ecosystem.resource_control.load_state", return_value=before), \
            patch("ecosystem.resource_control.enter_emergency", return_value={"mode": "emergency"}) as enter:
        result = resource_control.tick()
    assert result["mode"] == "emergency"
    assert enter.call_count == 1
    assert "increased from 0 to 1" in enter.call_args.args[2]


@with_root
def test_pressure_preempts_work_and_unloads_only_dynamic_models(_root):
    before = {"version": 1, "mode": "normal", "boot_id": "boot", "last_oom_kills": 0}
    current = {
        "at": "now", "boot_id": "boot", "oom_kills": 0,
        "memory_available_gb": 50.0, "swap_used_gb": 0.0,
        "memory_full_avg10": 0.0, "gtt_used_gb": 58.0,
    }
    systemctl_calls = []
    with patch("ecosystem.resource_control.resource_snapshot", return_value=current), \
            patch("ecosystem.resource_control.load_state", return_value=before), \
            patch("ecosystem.resource_control.checkpoint_running_jobs", return_value=["task-work"]) as checkpoint, \
            patch("ecosystem.resource_control.unload_dynamic_models", return_value=[{"model": "large", "ok": True}]) as unload, \
            patch("ecosystem.resource_control._user_systemctl",
                  side_effect=in_memory_systemctl(systemctl_calls)):
        with patch("ecosystem.resource_control.time.monotonic", return_value=100.0):
            first = resource_control.tick()
        assert first["mode"] == "normal"
        assert checkpoint.call_count == 0
        assert unload.call_count == 0
        with patch("ecosystem.resource_control.time.monotonic", return_value=105.0):
            result = resource_control.tick()
    assert result["mode"] == "pressure"
    assert result["pressure_interrupted_jobs"] == ["task-work"]
    assert checkpoint.call_count == 1
    assert unload.call_count == 1
    assert systemctl_calls[0] == ("stop", "agent-ecosystem.service")


@with_root
def test_pressure_stop_failure_halts_without_unloading_models(_root):
    state = normal_resource_state()
    with patch("ecosystem.resource_control.checkpoint_running_jobs",
               return_value=["task-work"]), \
            patch("ecosystem.resource_control._user_systemctl",
                  side_effect=in_memory_systemctl(failed_action="stop")), \
            patch("ecosystem.resource_control.unload_dynamic_models",
                  return_value=[{"model": "must-not-unload", "ok": True}]) as unload:
        result = resource_control.enter_pressure(
            state, pressure_snapshot(),
        )
    assert result["mode"] == "pressure"
    assert "stop" in result.get("pressure_error", "")
    assert unload.call_count == 0


@with_root
def test_pressure_release_restart_failure_keeps_dispatch_halted(root):
    interrupted = "task-interrupted"
    state = {
        **normal_resource_state(),
        "mode": "pressure",
        "healthy_since_monotonic": 0.0,
        "pressure_interrupted_jobs": [interrupted],
    }
    cli.atomic_json(root / "state/jobs" / f"{interrupted}.json", {
        "id": interrupted,
        "state": "interrupted",
        "resume_available": True,
    })
    central_policy = {
        "resource": {"healthy_release_seconds": 60.0, "poll_seconds": 0.75},
        "lifecycle": {"reconciliation_deadline_seconds": 19.0},
    }
    sleeps = []
    with patch.object(time_policy, "load", return_value=central_policy), \
            patch("ecosystem.resource_control.resource_snapshot",
                  return_value=healthy_snapshot()), \
            patch("ecosystem.resource_control.load_state", return_value=state), \
            patch("ecosystem.resource_control._user_systemctl",
                  side_effect=in_memory_systemctl(
                      missing_process_unit="agent-ecosystem.service")), \
            patch("ecosystem.resource_control.time.monotonic",
                  side_effect=(100.0, 100.0, 100.0, 160.0)), \
            patch("ecosystem.resource_control.time.sleep", side_effect=sleeps.append):
        result = resource_control.tick()

    assert result["mode"] == "pressure"
    assert "live process" in result["pressure_error"]
    assert read_job(root, interrupted)["state"] == "interrupted"
    assert sleeps == [0.75]


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(unittest.FunctionTestCase(function) for function in functions)
