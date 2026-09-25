import re

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
        base_path = roles / "_base.md"
        base = base_path.read_text(encoding="utf-8").strip() if base_path.is_file() else ""
        return {"label": label, "known": False, "context": base,
                "capabilities": ["tool-calling"]}
    return {"label": label, "known": True,
            "context": path.read_text(encoding="utf-8").strip(),
            "capabilities": role_capabilities(label)}


def load_role(role: str | None) -> str:
    """Compatibility wrapper returning safe advisory context without admission."""
    return resolve_role(role)["context"]


def build_prompt(role: str | None, task: str) -> str:
    """Compose an agent prompt: shared base, the role's guidance, then the task."""
    base = cli.ROOT / "roles/_base.md"
    parts = [base.read_text(encoding="utf-8").strip()] if base.is_file() else []
    resolved = resolve_role(role) if role else {"known": False}
    if resolved["known"] and resolved["context"]:
        parts.append(resolved["context"])
    parts = [part for part in parts if part]
    if not parts:
        return task.strip() + "\n"
    return "\n\n".join([*parts, "## Your assignment\n\n" + task.strip()]) + "\n"
