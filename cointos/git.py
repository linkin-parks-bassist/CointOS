"""Git: the one place CointOS runs it. Repositories, refs, cleanliness and task worktrees."""
from __future__ import annotations

import subprocess
from pathlib import Path


def result(repo, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def run(repo, *args) -> str:
    """Git's output; a failure raises ValueError with git's own explanation."""
    done = result(repo, *args)
    if done.returncode:
        raise ValueError(done.stderr.strip() or f"git {' '.join(args)} failed")
    return done.stdout.rstrip("\n")


def ok(repo, *args) -> bool:
    return result(repo, *args).returncode == 0


def head(repo, ref: str = "HEAD") -> str:
    return run(repo, "rev-parse", ref)


def contains(repo, commit: str, branch: str) -> bool:
    """Whether `branch` already contains `commit`."""
    return ok(repo, "merge-base", "--is-ancestor", commit, branch)


def clean(worktree) -> bool:
    """Whether a worktree has everything committed (a missing one is not clean)."""
    done = result(worktree, "status", "--porcelain")
    return done.returncode == 0 and not done.stdout.strip()


def blob(repo, commit: str, path: str) -> str | None:
    done = result(repo, "rev-parse", f"{commit}:{path}")
    return done.stdout.strip() if done.returncode == 0 else None


def show(repo, commit: str, path: str) -> str:
    """A file's content at a commit; empty when it does not exist there."""
    done = result(repo, "show", f"{commit}:{path}")
    return done.stdout if done.returncode == 0 else ""


def changed(repo, before: str, after: str) -> list[str]:
    """Paths changed between two commits. No rename detection: both names count."""
    if before == after:
        return []
    return [path for path in run(repo, "diff", "--no-renames", "--name-only", "-z", before, after).split("\0") if path]


# ---------------------------------------------------------------- task worktrees

def add_worktree(repo, worktree: str, branch: str, base: str) -> None:
    """A task's worktree on its own branch, created from `base` the first time."""
    if Path(worktree).is_dir():
        return
    Path(worktree).parent.mkdir(parents=True, exist_ok=True)
    if ok(repo, "rev-parse", "--verify", "--quiet", branch):
        run(repo, "worktree", "add", worktree, branch)
    else:
        run(repo, "worktree", "add", "-b", branch, worktree, base)


def remove_landed_worktree(repo, worktree: str, branch: str, main: str) -> bool:
    """Remove a worktree and its branch once main contains the branch; never unlanded work."""
    if not contains(repo, branch, main):
        return False
    result(repo, "worktree", "remove", "--force", worktree)
    result(repo, "branch", "-d", branch)
    return True


def discard_worktree(repo, worktree: str, branch: str) -> None:
    """Remove a worktree and branch whose work landed squashed, so main never contains the branch."""
    result(repo, "worktree", "remove", "--force", worktree)
    result(repo, "branch", "-D", branch)
