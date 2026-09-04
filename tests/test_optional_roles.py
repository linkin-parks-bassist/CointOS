import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ecosystem import cli, control_agent, control_runtime, control_turns, roles


def with_root(function):
    def run():
        with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "ROOT", Path(temporary)):
            root = Path(temporary)
            cli.initialize()
            (root / "roles").mkdir(exist_ok=True)
            (root / "roles/_base.md").write_text(
                "# Base Agent\n\n## Mission\nComplete the assigned task safely.\n",
                encoding="utf-8",
            )
            function(root)
    run.__name__ = function.__name__
    return run


def write_role(root: Path, role: str) -> None:
    (root / f"roles/{role}.md").write_text(
        f"# {role}\n\n## Mission\nUse the registered context.\n",
        encoding="utf-8",
    )


def read_job(root: Path, job_id: str) -> dict:
    return json.loads((root / f"state/jobs/{job_id}.json").read_text(encoding="utf-8"))


@with_root
def test_optional_and_unknown_roles_use_base_context(root):
    assert roles.resolve_role(None)["known"] is False
    assert "base agent" in roles.resolve_role(None)["context"].lower()
    resolved = roles.resolve_role("novel_specialist")
    assert resolved["label"] == "novel_specialist"
    assert resolved["known"] is False
    assert "base agent" in resolved["context"].lower()


@with_root
def test_known_underscored_role_is_loaded(root):
    write_role(root, "sole_survivor")
    assert roles.resolve_role("sole_survivor")["known"] is True


@with_root
def test_path_like_role_never_becomes_a_path(root):
    resolved = roles.resolve_role("../../etc/passwd")
    assert resolved["label"] == "../../etc/passwd"
    assert resolved["known"] is False
    assert "passwd" not in resolved["context"]


@with_root
def test_control_plane_role_file_is_not_spawnable_context(root):
    write_role(root, "_control-plane")
    resolved = roles.resolve_role("_control-plane")
    assert resolved["known"] is False
    assert "registered context" not in resolved["context"]


@with_root
def test_enqueue_unknown_role_does_not_fail(root):
    job_id = cli.enqueue_task(
        "mathematical_mongoose", "inspect the invariant", agent_name="Noether"
    )
    assert read_job(root, job_id)["role"] == "mathematical_mongoose"


@with_root
def test_enqueue_without_role_uses_a_safe_identity_fallback(root):
    job_id = cli.enqueue_task(None, "inspect the invariant")
    job = read_job(root, job_id)
    assert job["role"] is None
    assert job["agent_name"].startswith("agent-")


@with_root
def test_unsafe_role_label_does_not_reach_identity_generation(root):
    generated_for = []

    def generate(role, _task):
        generated_for.append(role)
        return "Noether"

    with patch("ecosystem.identity.generate", side_effect=generate):
        job_id = cli.enqueue_task("../../etc/passwd", "inspect the invariant")
    assert generated_for == ["agent"]
    assert read_job(root, job_id)["role"] == "../../etc/passwd"


@with_root
def test_deep_control_preserves_unknown_role_label(root):
    control_turns.accept(7, 42, 42, "inspect the invariant")
    arguments = {
        "role": "mathematical_mongoose",
        "task": "inspect the invariant",
        "agent_name": "Noether",
    }
    with patch("ecosystem.control_runtime.snapshot", return_value={"models": []}):
        result = control_runtime.execute_tool("telegram-7", "queue_task", arguments)
    assert result["ok"] is True
    job_path = next((root / "state/jobs").glob("task-*.json"))
    assert json.loads(job_path.read_text(encoding="utf-8"))["role"] == "mathematical_mongoose"


@with_root
def test_deep_control_accepts_omitted_role(root):
    control_turns.accept(8, 42, 42, "inspect the invariant")
    arguments = {"task": "inspect the invariant", "agent_name": "Noether"}
    with patch("ecosystem.control_runtime.snapshot", return_value={"models": []}):
        result = control_runtime.execute_tool("telegram-8", "queue_task", arguments)
    assert result["ok"] is True
    job_path = next((root / "state/jobs").glob("task-*.json"))
    assert json.loads(job_path.read_text(encoding="utf-8"))["role"] is None


@with_root
def test_status_formats_absent_role_as_unassigned(root):
    cli.atomic_json(root / "state/jobs/task-null.json", {
        "id": "task-null",
        "kind": "agent-task",
        "state": "queued",
        "role": None,
        "model": None,
    })
    status = control_runtime.status_text()
    assert "queued / unassigned / unspecified" in status
    assert " / None / " not in status


@with_root
def test_unsafe_role_label_is_absent_from_live_control_prompt(root):
    cli.atomic_json(root / "state/jobs/task-unsafe.json", {
        "id": "task-unsafe",
        "kind": "agent-task",
        "state": "queued",
        "role": "../../etc/passwd",
        "agent_name": "Noether",
        "model": None,
        "created_at": "2026-09-04T00:00:00+00:00",
        "updated_at": "2026-09-04T00:00:00+00:00",
    })
    captured = {}

    def infer(**arguments):
        captured.update(arguments)
        return {"content": None, "tool_calls": [{
            "id": "done",
            "type": "function",
            "function": {"name": "finish_silently", "arguments": "{}"},
        }]}

    with patch("ecosystem.control_runtime.snapshot", return_value={"models": []}), \
            patch("ecosystem.control_agent.active_chat_model", return_value="model"):
        live = control_runtime.live_context()
        control_agent.respond("status?", [], "I’ll check.", live,
                              lambda *_arguments: {}, infer=infer)
    prompt = captured["messages"][0]["content"]
    assert "../../etc/passwd" not in prompt
    assert "task-unsafe" in prompt


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(unittest.FunctionTestCase(function) for function in functions)
