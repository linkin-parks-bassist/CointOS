"""Knowledge trees and their health, for the gardener.

A tree is a knowledge root, not a project: a repository can hold several trees and a tree
need not belong to any project. CointOS tends the trees named in its config, each in a
worktree of the repository that holds it, landing on that repository's main branch.
"""
from __future__ import annotations

import hashlib
import random
import subprocess
from pathlib import Path


def parse(output: str) -> dict:
    """`kt status` output as {"brown", "yellow", "leaves", "hash"}: the counts of leaves needing
    care, the lines naming them (brown first), and a digest that changes when they do. Pure."""
    leaves = [line for line in output.splitlines() if line.startswith(("brown\t", "yellow\t"))]
    return {"brown": sum(line.startswith("brown\t") for line in leaves),
            "yellow": sum(line.startswith("yellow\t") for line in leaves), "leaves": leaves,
            "hash": hashlib.sha256("\n".join(leaves).encode()).hexdigest()[:16]}


def root(tree: dict, checkout: str | None = None) -> Path:
    """The tree's root in the repository's main checkout, or in `checkout` (a task worktree)."""
    return Path(checkout or tree["path"]) / tree["tree"]


def health(tree: dict, timeout: float) -> dict:
    """The tree's health on its main checkout, read with `kt status` (which runs no proofs)."""
    result = subprocess.run(["kt", "status", "--root", str(root(tree))], cwd=tree["path"], capture_output=True,
                            text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"kt status failed for {tree['name']}: {(result.stderr or result.stdout).strip()}")
    return parse(result.stdout)


def rank(health: dict) -> list:
    """Where gardening the tree stands among tasks (lower runs first, see `schema.KINDS`): brown
    leaves before landing and all queued work, yellow ones before queued work (even the top of
    the queue), a routine pass with the surveys; the worse the tree, the sooner."""
    if health["brown"]:
        return [0, -health["brown"], -health["yellow"]]
    if health["yellow"]:
        return [3, -health["yellow"]]
    return [7]


def pending(health: dict) -> list[str]:
    """Root-relative paths needing verification, in health priority order."""
    return [line.split("\t")[1].split(":", 1)[1] for line in health["leaves"]]


def select(health: dict, leaves: list[str], limit: int) -> list[str]:
    """A bounded repair batch, or a random routine sample when the tree is green."""
    return pending(health)[:limit] if health["leaves"] else random.sample(sorted(leaves), min(limit, len(leaves)))
