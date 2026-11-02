"""Git: the one place CointOS runs it. Repositories, refs, cleanliness and task worktrees."""
from __future__ import annotations

import subprocess
import contextlib
import fcntl
import os
import re
import secrets
import tempfile
from pathlib import Path


@contextlib.contextmanager
def repository_lock(repo):
    """Serialize CointOS's publications, including maintenance and worker landings."""
    common = run(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    with open(Path(common) / "cointos-land.lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("another CointOS publication owns this repository; "
                             "no publication started; retry after it finishes") from error
        yield


def publish(repo, main: str, commit: str, expected: str) -> dict:
    """Advance the accepted ref by compare-and-swap, preserving editor workspaces.

    Caller holds repository_lock. A dirty checkout of main moves to a draft branch
    at its existing HEAD; its index and files are never stashed, reset or merged.
    A clean checkout detaches briefly and refreshes after publication. Checkouts
    already on another branch are independent of the accepted ref.
    """
    recover_publications(repo)
    if head(repo, main) != expected:
        raise ValueError("main changed; review and retry publication")
    if not contains(repo, expected, commit):
        raise ValueError("publication must contain current main")
    if commit == expected:
        return {"commit": commit}
    checkouts = []
    for block in run(repo, "worktree", "list", "--porcelain", "-z").split("\0\0"):
        fields = dict(line.split(" ", 1) if " " in line else (line, "") for line in block.split("\0"))
        if fields.get("branch") == f"refs/heads/{main}":
            checkouts.append(fields["worktree"])
    if len(checkouts) > 1:
        raise ValueError("main is checked out more than once; repair the checkout ownership")
    checkout = checkouts[0] if checkouts else None
    draft = None
    if checkout:
        if head(checkout) != expected:
            raise ValueError("main checkout changed; retry publication")
        if not clean(checkout):
            draft = draft_checkout(checkout, main, expected)
        else:
            run(checkout, "switch", "-q", "--detach", expected)
    try:
        # Never force a checked-out branch forward behind its index. Once
        # detached/drafted, Git can atomically check and update the main ref.
        run(repo, "update-ref", f"refs/heads/{main}", commit, expected)
    finally:
        if checkout and not draft:
            # Ref publication and receipt settlement must not become dependent
            # on refreshing a workspace. Git refuses refresh if new local work
            # would be overwritten; it stays safely detached in that case.
            refreshed = result(checkout, "switch", "-q", main)
            if refreshed.returncode:
                draft = run(checkout, "branch", "--show-current") or "detached"
    return {"commit": commit, **({"workspace": checkout, "draft": draft} if draft else {})}


def draft_checkout(checkout, main: str, expected: str) -> str:
    """Move symbolic HEAD to a draft without racing an editor's commit.

    Git 2.43 has no symbolic-ref compare-and-swap transaction. Its HEAD.lock
    protocol protects commits through HEAD while we check its identity and
    atomically replace it. Only that identity changes: files, index and merge
    metadata stay intact. This does not lock arbitrary edits to those files.
    Caller holds repository_lock and has recovered prior publication artifacts.
    """
    target = Path(run(checkout, "rev-parse", "--path-format=absolute", "--git-path", "HEAD"))
    lock = target.with_name(target.name + ".lock")
    owned = target.with_name(target.name + ".cointos-publication")
    pending = owned.open("x", encoding="utf-8")
    identity = os.fstat(pending.fileno())
    try:
        with pending:
            try:
                # The ownership proof exists before HEAD.lock can exist, even
                # if this process dies at the link boundary.
                os.link(owned, lock)
            except FileExistsError as error:
                raise ValueError("main workspace HEAD is locked by another Git operation; retry publication") from error
            os.fchmod(pending.fileno(), target.stat().st_mode & 0o777)
            if (head(checkout) != expected
                    or run(checkout, "symbolic-ref", "--quiet", "HEAD") != f"refs/heads/{main}"):
                raise ValueError("main workspace changed; retry publication")
            draft = f"work/draft-{secrets.token_hex(6)}"
            run(checkout, "branch", draft, expected)
            pending.write(f"ref: refs/heads/{draft}\n")
            pending.flush()
            os.fsync(pending.fileno())
        os.replace(lock, target)
        return draft
    finally:
        # A Git operation can create its own lock immediately after replacement;
        # cleanup must never remove that writer's lock.
        try:
            remaining = lock.stat()
        except FileNotFoundError:
            pass
        else:
            if (remaining.st_dev, remaining.st_ino) == (identity.st_dev, identity.st_ino):
                lock.unlink()
        owned.unlink(missing_ok=True)


def recover_publications(repo) -> None:
    """Remove only abandoned CointOS HEAD locks; caller holds repository_lock.

    Winning the existing publication lock proves no earlier CointOS publisher
    still owns a handoff. A hard link proves which HEAD.lock it created. An
    external Git lock with a different inode is never removed.
    """
    for block in run(repo, "worktree", "list", "--porcelain", "-z").split("\0\0"):
        fields = dict(line.split(" ", 1) if " " in line else (line, "") for line in block.split("\0"))
        checkout = fields.get("worktree")
        if not checkout or not Path(checkout).is_dir():
            continue
        target = Path(run(checkout, "rev-parse", "--path-format=absolute", "--git-path", "HEAD"))
        owned = target.with_name(target.name + ".cointos-publication")
        lock = target.with_name(target.name + ".lock")
        try:
            identity = owned.stat()
        except FileNotFoundError:
            continue
        try:
            remaining = lock.stat()
        except FileNotFoundError:
            pass
        else:
            if os.path.samestat(identity, remaining):
                lock.unlink()
        owned.unlink()


def result(repo, *args) -> subprocess.CompletedProcess:
    # Mechanical operations have explicit test/receipt authority. Local hooks
    # must not add unbounded scripts or extra gates to that control path.
    return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", str(repo), *args],
                          capture_output=True, text=True)


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


_HUNK = re.compile(rb"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)


def _hunks(base: bytes, side: bytes, *flags: str) -> list[tuple[int, int, list[bytes]]]:
    """One side's own changes against the base: (first base line, end, new lines)."""
    with tempfile.TemporaryDirectory(prefix="cointos-merge-") as temp:
        old, new = Path(temp) / "old", Path(temp) / "new"
        old.write_bytes(base)
        new.write_bytes(side)
        diff = subprocess.run(["git", "diff", "--no-index", "--no-color", "-U0", "--diff-algorithm=histogram",
                               *flags, "--", str(old), str(new)], capture_output=True).stdout
    lines, found = side.splitlines(keepends=True), []
    for hunk in _HUNK.finditer(diff):
        start, removed, at, added = int(hunk[1]), int(hunk[2] or 1), int(hunk[3]), int(hunk[4] or 1)
        first = start if removed == 0 else start - 1
        found.append((first, first + removed, lines[at - 1:at - 1 + added] if added else []))
    return found


def _compose(base: bytes, current: bytes, packet: bytes, *flags: str) -> bytes | None:
    """Apply both sides' changes to the base, or None if they edit the same base lines.

    Each side is diffed against the base on its own. Git's merge also aligns the two
    sides with each other, so similar new helpers inserted at one spot shatter into
    overlapping regions. Inserted against the base they are two whole blocks, current first.
    """
    def includes(lines, block):
        return any(lines[n:n + len(block)] == block for n in range(len(lines) - len(block) + 1))

    lines = base.splitlines(keepends=True)
    ours, theirs, out, position = _hunks(base, current, *flags), _hunks(base, packet, *flags), [], 0
    while ours or theirs:
        mine, other = ours[0] if ours else None, theirs[0] if theirs else None
        if mine and other and mine[:2] == other[:2]:
            ours, theirs = ours[1:], theirs[1:]
            if mine[2] == other[2]:
                new = mine[2]
            elif mine[0] != mine[1]:  # two different replacements of one region
                return None
            elif includes(mine[2], other[2]):  # already present: retain the block once
                new = mine[2]
            elif includes(other[2], mine[2]):
                new = other[2]
            else:
                new = mine[2] + other[2]
            hunk = (mine[0], mine[1], new)
        elif mine and other and mine[0] < other[1] and other[0] < mine[1]:
            return None
        elif mine and (not other or mine[:2] <= other[:2]):
            hunk, ours = mine, ours[1:]
        else:
            hunk, theirs = other, theirs[1:]
        out += lines[position:hunk[0]] + hunk[2]
        position = hunk[1]
    return b"".join(out + lines[position:])


def resolve_insertions(repo, paths: list[str]) -> None:
    """Compose concurrent changes to protected files without choosing between edits.

    Only regular files with identical modes qualify. A whole inserted block already
    present in the other side is retained once, so squash merges can be repeated without
    relying on the packet commit's ancestry. Recompute from index blobs, not editable
    conflict markers. If only a reindent overlaps, the current side's whitespace stands;
    two real edits of the same lines, a deletion or a binary file stay for their owner.
    """
    for name in paths:
        entries = [line.split("\t", 1)[0].split() for line in
                   run(repo, "ls-files", "-u", "--", name).splitlines()]
        if len(entries) != 3 or {e[2] for e in entries} != {"1", "2", "3"}:
            continue
        if len({e[0] for e in entries}) != 1 or entries[0][0] not in {"100644", "100755"}:
            continue
        current, base, packet = (subprocess.check_output(["git", "-C", str(repo), "show", f":{stage}:{name}"])
                                 for stage in (2, 1, 3))
        if b"\0" in current + base + packet:
            continue
        composed = _compose(base, current, packet)
        if composed is None:
            composed = _compose(base, current, packet, "--ignore-all-space")
        if composed is None:
            continue
        (Path(repo) / name).write_bytes(composed)
        run(repo, "add", "--", name)


# ---------------------------------------------------------------- task worktrees

SCRATCH = re.compile(r"/state/agents/[^/]+/scratch/")


def free_from_scratch(repo, branch: str) -> None:
    """A run's throwaway checkout must not stop a branch's owner from starting.

    Git allows a branch in one worktree at a time, and any run can leave a branch checked out in
    its scratch directory. Detaching keeps that checkout and its files, and only lets go of the name.
    """
    run(repo, "worktree", "prune")
    path = None
    for line in run(repo, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line == f"branch refs/heads/{branch}" and path and SCRATCH.search(path):
            run(path, "checkout", "-q", "--detach")


def add_worktree(repo, worktree: str, branch: str, base: str) -> None:
    """A task's worktree on its own branch, created from `base` the first time."""
    if Path(worktree).is_dir():
        return
    Path(worktree).parent.mkdir(parents=True, exist_ok=True)
    if ok(repo, "rev-parse", "--verify", "--quiet", branch):
        free_from_scratch(repo, branch)
        run(repo, "worktree", "add", worktree, branch)
    else:
        run(repo, "worktree", "add", "-b", branch, worktree, base)


ARCHIVE = "refs/cointos/archive/"


def remove_worktree(repo, worktree: str) -> None:
    """Remove a task's checkout; its branch keeps the commits and `add_worktree` can recreate it."""
    result(repo, "worktree", "remove", "--force", worktree)
    result(repo, "worktree", "prune")


def retire_branch(repo, branch: str, main: str, keep: bool) -> str:
    """Settle a finished task's branch: deleted once main contains it, else archived under
    ARCHIVE (commits stay reachable) unless `keep`. Returns what happened."""
    if not ok(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"):
        return "absent"
    if contains(repo, branch, main):
        run(repo, "branch", "-D", branch)
        return "landed"
    if keep:
        return "kept"
    run(repo, "update-ref", ARCHIVE + branch, f"refs/heads/{branch}")
    run(repo, "branch", "-D", branch)
    return "archived"
