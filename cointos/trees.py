"""Knowledge trees and their health, for the gardener.

A tree is a knowledge root, not a project: a repository can hold several trees and a tree
need not belong to any project. CointOS tends the trees named in its config, each in a
worktree of the repository that holds it, landing on that repository's main branch.
"""
from __future__ import annotations

import hashlib
import random
import re
import subprocess
from pathlib import Path

from cointos import git


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
    found = parse(result.stdout)
    try:
        committed = inventory(tree)
        found['inventory'] = available_inventory(tree, committed)
    except ValueError as error:
        raise RuntimeError(f"cannot read {tree['name']} maintenance snapshot: {error}") from error
    found['deferred'] = sorted((set(committed) | set(pending(found))) - set(found['inventory']))
    return found


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


def inventory(tree: dict) -> list[str]:
    """The tree's leaves as committed on its main branch — the base a garden worktree is built
    from — so a batch never names a leaf the worktree cannot see. Uncommitted or untracked
    working-tree leaves are excluded: they are not in the worktree, and naming them would send a
    gardener after a phantom address."""
    prefix = tree["tree"] + "/"
    files = git.run(tree["path"], "ls-tree", "-r", "--name-only", tree["main_branch"], tree["tree"]).splitlines()
    return sorted(name[len(prefix):] for name in files if name.startswith(prefix) and name.endswith(".md"))


def select(health: dict, leaves: list[str], limit: int) -> list[str]:
    """A bounded repair batch, or a random routine sample when the tree is green."""
    available = set(leaves)
    return ([name for name in pending(health) if name in available][:limit] if health["leaves"]
            else random.sample(sorted(leaves), min(limit, len(leaves))))


def available_inventory(tree: dict, committed: list[str] | None = None) -> list[str]:
    """Committed answers without newer canonical body/policy drafts."""
    names = inventory(tree) if committed is None else committed
    edits = set(answer_edits(tree['path'], [tree['tree'] + '/' + name for name in names]))
    return [name for name in names if tree['tree'] + '/' + name not in edits]


def answer_edits(repo, paths: list[str]) -> list[str]:
    """Answers/policy pending in the canonical checkout or index, not health stamps.

    A branch built from main cannot reconcile a newer draft on the owner's behalf.
    Missing baseline/index/files are distinct; new leaves are safe only when absent
    from both canonical files and index. No checkout, index or refs are changed.
    """
    def content(text):
        if text is None:
            return None
        match = re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)', text, re.S)
        if not match:
            return ('', text.strip())
        metadata = re.sub(r'^(?:status|checked_at|revised_at):[^\n]*(?:\n|$)', '',
                          match[1], flags=re.M).strip()
        return metadata, text[match.end():].strip()

    repo = Path(repo).resolve()
    base = git.head(repo)  # an editor branch may legitimately differ from accepted main
    conflicts = []
    for name in sorted(set(paths)):
        def at(ref):
            result = git.result(repo, 'show', f'{ref}:{name}')
            return result.stdout if result.returncode == 0 else None
        try:
            original, staged = content(at(base)), content(at(''))
            if staged is None and git.run(repo, 'ls-files', '--', name):
                raise ValueError('index entry is not readable at stage zero')
            path = repo / name
            if path.is_symlink() or not path.resolve().is_relative_to(repo):
                raise ValueError('answer path escapes its repository')
            current = content(path.read_text()) if path.exists() else None
            if staged != original or current != original:
                conflicts.append(name)
        except (OSError, ValueError):
            conflicts.append(name)
    return conflicts
