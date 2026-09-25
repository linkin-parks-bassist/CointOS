"""Deterministic acceptance checks independent of executor state transitions."""
from __future__ import annotations

from pathlib import Path


def artifact_failure(contract: object) -> str | None:
    """Return the failure for declared artifact checks, or ``None``.

    Other acceptance kinds belong to their own owners. An absent/default
    acceptance list does not claim semantic completion; it merely contributes no
    deterministic artifact failure.
    """
    if type(contract) is not dict:
        return None
    acceptance = contract.get("acceptance")
    if type(acceptance) is not list:
        return None
    failures: list[str] = []
    for index, item in enumerate(acceptance):
        if type(item) is not dict or item.get("kind") != "artifact":
            continue
        path = item.get("path")
        if type(path) is not str or not path:
            failures.append(f"artifact acceptance item {index} has no explicit path")
            continue
        artifact = Path(path)
        if not artifact.is_file():
            failures.append(f"missing artifact: {path}")
        elif artifact.stat().st_size == 0:
            failures.append(f"empty artifact: {path}")
    if not failures:
        return None
    return "acceptance failed: " + "; ".join(failures)
