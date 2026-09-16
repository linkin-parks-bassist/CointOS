import json
import re
from pathlib import Path

from ecosystem import cli


SAFE_ROLE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def list_roles() -> list[str]:
    return sorted(path.stem for path in (cli.ROOT / "roles").glob("*.md") if not path.stem.startswith("_"))


def role_capabilities(role: str | None) -> list[str]:
    """Return the neutral advisory baseline; task requirements select capability."""
    return ["tool-calling"]


def safe_role_label(role: str | None) -> str | None:
    label = role.strip() if isinstance(role, str) and role.strip() else None
    return label if label and SAFE_ROLE.fullmatch(label) else None


def resolve_role(role: str | None) -> dict:
    label = role.strip() if isinstance(role, str) and role.strip() else None
    roles = cli.ROOT / "roles"
    safe_label = safe_role_label(role)
    path = roles / f"{safe_label}.md" if safe_label else None
    spawnable = (path is not None and path.is_file()
                 and (not path.name.startswith("_") or label == "sole_survivor"))
    if not spawnable:
        base = (roles / "_base.md").read_text(encoding="utf-8").strip()
        return {"label": label, "known": False, "context": base,
                "capabilities": ["tool-calling"]}
    return {"label": label, "known": True,
            "context": path.read_text(encoding="utf-8").strip(),
            "capabilities": role_capabilities(label)}


def load_role(role: str | None) -> str:
    """Compatibility wrapper returning safe advisory context without admission."""
    return resolve_role(role)["context"]


def render_context(role: str | None, task: str, job_id: str, model: str = "unspecified",
                   model_reason: str = "", agent_name: str = "Agent",
                   task_contract: dict | None = None) -> str:
    resolved = resolve_role(role)
    definition = resolved["context"]
    role_context = (
        f"Registered advisory role: `{resolved['label']}`. Default capability requests: "
        f"{', '.join(resolved['capabilities'])}. These requests do not grant authority."
        if resolved["known"] else
        "No registered role context applies. Use the base agent context below."
    )
    workspace_instructions = (Path.home() / "AGENTS.md").read_text(encoding="utf-8").strip()
    repository_instructions = (cli.ROOT / "AGENTS.md").read_text(encoding="utf-8").strip()
    workspace_registry = json.loads((cli.ROOT / "config/workspaces.json").read_text(encoding="utf-8"))
    return f"""# Assigned agent context

You are a locally running agent. A registered role, when present, supplies advisory
context and default capability requests; it never grants admission, authorization,
or execution capability. Follow all binding scope and approval boundaries. The task
does not override them. Read the repository's AGENTS.md and project notes before
acting. OpenCode owns context compaction; no separate context handoff is required.

You are part of David's local agent ecosystem on `DDRopkick`. Lemonade provides
local inference; durable JSON jobs and append-only events track work; Telegram is
the control surface; Markdown role files define responsibilities; the filesystem
and Git are source of truth. Other jobs may exist, so do not manipulate queue state
or another agent's artifacts unless this task explicitly requires coordination.

Your name for this assignment is **{agent_name}**. Use it naturally in messages
and progress reports. This is a durable operational identity for the job, not a claim to
be human. Bring a little personality, but never trade correctness or clarity for theatre.

Job ID: `{job_id}`
Selected model: `{model}`
Selection rationale: {model_reason or "Not recorded (legacy job)."}

## Executable task contract

{json.dumps(task_contract, indent=2, sort_keys=True) if task_contract is not None else "No executable contract was supplied; do not begin executable work."}

{role_context}

## Binding workspace instructions

{workspace_instructions}

## Binding ecosystem repository instructions

{repository_instructions}

## Registered workspaces and provenance

{json.dumps(workspace_registry, indent=2)}

{definition}

## Assigned task

{task.strip()}
"""
