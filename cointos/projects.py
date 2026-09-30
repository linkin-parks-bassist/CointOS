"""Validation and atomic mutation of CointOS's durable project registry."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from cointos import git
from cointos.config import PROJECTS, write_json

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def normalize(project: dict) -> dict:
    name = str(project.get("name", "")).strip()
    if not NAME.fullmatch(name):
        raise ValueError("project name must use letters, numbers, dot, underscore or dash")
    path = Path(str(project.get("path", ""))).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"project path does not exist: {path}")
    top = git.result(path, "rev-parse", "--show-toplevel")
    if top.returncode or Path(top.stdout.strip()).resolve() != path:
        raise ValueError(f"project path is not a Git repository root: {path}")
    current = git.result(path, "branch", "--show-current").stdout.strip()
    branch = str(project.get("main_branch") or current or "main").strip()
    if not branch or any(c.isspace() for c in branch):
        raise ValueError("main branch must be one non-empty Git ref name")
    priority = project.get("priority", 100)
    if isinstance(priority, bool) or not isinstance(priority, int):
        raise ValueError("project priority must be an integer; lower runs first")
    result = {"name": name, "path": str(path), "main_branch": branch,
              "priority": priority, "enabled": bool(project.get("enabled", True))}
    if project.get("test_policy") is not None:
        policy = project["test_policy"]
        if not isinstance(policy, dict) or not isinstance(policy.get("manifest"), str):
            raise ValueError("test_policy must be an object with a manifest path")
        if not all(isinstance(policy.get(key, []), list) and all(isinstance(v, str) for v in policy.get(key, []))
                   for key in ("protected", "non_code")):
            raise ValueError("test_policy protected and non_code must be string lists")
        result["test_policy"] = policy
    return result


def write(config: dict, path: Path = PROJECTS) -> None:
    ordered = sorted(config["projects"], key=lambda p: (p.get("priority", 100), p["name"].lower()))
    write_json(path, {"version": 1, "projects": ordered})
    config["projects"][:] = ordered


def add(config: dict, project: dict, path: Path = PROJECTS) -> dict:
    if not str(project.get("name", "")).strip() and project.get("path"):
        project = {**project, "name": Path(str(project["path"])).expanduser().name}
    candidate = normalize(project)
    if any(p["name"].lower() == candidate["name"].lower() for p in config["projects"]):
        raise ValueError(f"project {candidate['name']!r} is already registered")
    if any(Path(p["path"]).resolve() == Path(candidate["path"]) for p in config["projects"]):
        raise ValueError(f"repository {candidate['path']} is already registered")
    config["projects"].append(candidate)
    write(config, path)
    return candidate


def create(config: dict, project: dict, registry_path: Path = PROJECTS) -> dict:
    name = str(project.get("name", "")).strip()
    if not NAME.fullmatch(name):
        raise ValueError("project name must use letters, numbers, dot, underscore or dash")
    target = Path(str(project.get("path") or (Path.home() / "Projects" / name))).expanduser().resolve()
    if target.exists() and any(target.iterdir()):
        raise ValueError(f"project directory is not empty: {target}")
    target.mkdir(parents=True, exist_ok=True)
    branch = str(project.get("main_branch") or "main")
    initialized = git.result(target, "init", "-b", branch)
    if initialized.returncode:
        raise ValueError(initialized.stderr.strip() or "git init failed")
    orientation = (f"{name} is a CointOS-managed project in {target}. "
                   "where/ owns orientation; what/is/the/spec.md owns requirements; "
                   "what/is/the/plan.md owns the remaining frontier; what/is/broken.md owns known defects.")
    initialized = subprocess.run(["kt", "init", "--project", orientation], cwd=target, capture_output=True, text=True)
    if initialized.returncode:
        raise ValueError(initialized.stderr.strip() or "kt init --project failed")
    staged = git.result(target, "add", ".knowledge")
    committed = git.result(target, "commit", "-m", "Initialize project") if not staged.returncode else staged
    if committed.returncode:
        raise ValueError("project was created, but its initial knowledge-tree commit failed; fix Git identity/state, "
                         "commit it, then use cointos project add")
    return add(config, {**project, "name": name, "path": str(target), "main_branch": branch}, registry_path)


def update(config: dict, name: str, changes: dict, path: Path = PROJECTS) -> dict:
    project = next((p for p in config["projects"] if p["name"].lower() == name.lower()), None)
    if project is None:
        raise ValueError(f"unknown project {name!r}")
    allowed = {"main_branch", "priority", "enabled", "test_policy"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError("unsupported project settings: " + ", ".join(sorted(unknown)))
    candidate = normalize({**project, **changes})
    project.clear()
    project.update(candidate)
    write(config, path)
    return candidate


def remove(config: dict, name: str, path: Path = PROJECTS) -> dict:
    project = next((p for p in config["projects"] if p["name"].lower() == name.lower()), None)
    if project is None:
        raise ValueError(f"unknown project {name!r}")
    config["projects"].remove(project)
    write(config, path)
    return project
