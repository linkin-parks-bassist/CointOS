import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ecosystem import cli, resource_control
from ecosystem.models import (
    _routing_prompt,
    admission,
    admitted_or_substitute,
    context_options,
    required_labels,
    role_compatible,
    route,
)


def with_root(function):
    def run():
        with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "ROOT", Path(temporary)):
            cli.initialize()
            function(Path(temporary))
    run.__name__ = function.__name__
    return run


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
