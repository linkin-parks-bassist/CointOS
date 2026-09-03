from pathlib import Path

from ecosystem import cli


def list_roles() -> list[str]:
    return sorted(path.stem for path in (cli.ROOT / "roles").glob("*.md"))


def load_role(role: str) -> str:
    if not role.replace("-", "").isalnum():
        raise ValueError("invalid role name")
    path = cli.ROOT / "roles" / f"{role}.md"
    if not path.is_file():
        raise ValueError(f"unknown role {role!r}; available: {', '.join(list_roles())}")
    content = path.read_text(encoding="utf-8").strip()
    required = ("## Mission", "## Permissions", "## Approval required", "## Handoff")
    missing = [heading for heading in required if heading not in content]
    if missing:
        raise ValueError(f"role {role!r} is missing: {', '.join(missing)}")
    return content


def render_context(role: str, task: str, job_id: str, model: str = "unspecified", model_reason: str = "") -> str:
    definition = load_role(role)
    return f"""# Assigned agent context

You are a locally running agent assigned the role below. Follow the role's scope
and approval boundaries. The task does not override those boundaries. Read the
repository's AGENTS.md and project notes before acting. Leave the required handoff.

Job ID: `{job_id}`
Selected model: `{model}`
Selection rationale: {model_reason or "Not recorded (legacy job)."}

{definition}

## Assigned task

{task.strip()}
"""
