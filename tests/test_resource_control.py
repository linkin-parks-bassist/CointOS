import json
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
            "pressure_confirmation_seconds": 5.0,
            "emergency_confirmation_seconds": 10.0,
            "healthy_release_seconds": 2.0,
        },
    }
    with patch("ecosystem.resource_control.resource_snapshot", return_value=healthy_snapshot()), \
            patch("ecosystem.resource_control.load_state", return_value=state), \
            patch.object(time_policy, "load", return_value=central_policy), \
            patch("ecosystem.resource_control._user_systemctl"):
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
                  side_effect=lambda *arguments: systemctl_calls.append(arguments)), \
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
                  side_effect=lambda *arguments: systemctl_calls.append(arguments)), \
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
                  side_effect=lambda *arguments: systemctl_calls.append(arguments)), \
            patch("ecosystem.resource_control.os.sync"):
        result = resource_control.advance_emergency(state, healthy_snapshot(), "legacy retry")

    assert result["emergency_phase"] == "active"
    assert read_job(root, result["sole_survivor_job"])["state"] == "ready"
    assert "agent-telegram.service" not in systemctl_units(systemctl_calls)
    assert "agent-notifier.service" not in systemctl_units(systemctl_calls)


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
                          side_effect=lambda *arguments: systemctl_calls.append(arguments)), \
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
                          side_effect=lambda *arguments: systemctl_calls.append(arguments)), \
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
    with patch("ecosystem.resource_control.resource_snapshot", return_value=current), \
            patch("ecosystem.resource_control.load_state", return_value=before), \
            patch("ecosystem.resource_control.checkpoint_running_jobs", return_value=["task-work"]) as checkpoint, \
            patch("ecosystem.resource_control.unload_dynamic_models", return_value=[{"model": "large", "ok": True}]) as unload, \
            patch("ecosystem.resource_control._user_systemctl") as systemctl:
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
    systemctl.assert_called_once_with("stop", "agent-ecosystem.service")


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(unittest.FunctionTestCase(function) for function in functions)
