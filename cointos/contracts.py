"""Test packets: the tests a piece of code travels with, and the suite it must not break.

A project's test policy names its contract manifest (a JSON list of {"covers", "command"}),
the protected test paths and the non-code paths. A test writer's commit registers a packet's
tests. Tests that already pass on main (`passing`) land at once; failing ones stay off main,
hidden from the implementer, until they land with the code that passes them. `packet_check`
runs them when the implementer finishes; `suite` runs every registered command on a landing
candidate.
"""
from __future__ import annotations

import contextlib
import fnmatch
import json
import os
import re
from pathlib import Path
import signal
import secrets
import subprocess
import tempfile
import time

from cointos import git

OUTPUT_LIMIT = 1 << 20  # output tail kept for red-check literals and failure details


def matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def protected(path: str, rules: dict) -> bool:
    return path == rules["manifest"] or matches(path, rules.get("protected", []))


def production(repo, before, after, rules) -> list[str]:
    """The changed paths that are production code: neither protected tests/harness nor non-code."""
    return sorted(p for p in git.changed(repo, before, after)
                  if not protected(p, rules) and not matches(p, rules.get("non_code", [])))


def contracts(repo, commit, rules) -> list[dict]:
    try:
        data = json.loads(git.run(repo, "show", f"{commit}:{rules['manifest']}"))
    except (ValueError, TypeError) as error:
        raise ValueError(f"accepted test contracts missing/invalid at {rules['manifest']}: {error}") from error
    if not isinstance(data, list) or not data:
        raise ValueError("test contract manifest must be a nonempty list")
    for contract in data:
        if (not isinstance(contract, dict) or set(contract) != {"covers", "command"}
                or any(not isinstance(contract.get(k), list) or not contract[k]
                       or any(not isinstance(s, str) or not s for s in contract[k]) for k in ("covers", "command"))):
            raise ValueError("each test contract requires nonempty covers and command string arrays")
        if any(s.startswith("/") or ".." in s.split("/") for s in contract["covers"]):
            raise ValueError("test coverage targets must be repository-relative")
    return data


def stage_history(repo, worker, main, rules):
    """Enforce edit ownership on the task's commits, excluding history already on main.

    The pinned base bounds the assignment; it is not a diff baseline after main advances.
    Importing main is legal. Inventing a forbidden merge resolution or reverting an earlier
    forbidden edit does not erase that edit from the assignment's history.
    """
    tests_only = worker["stage"] == "test-contract"
    def forbidden(path):
        return (not protected(path, rules) and not matches(path, rules.get("non_code", []))
                if tests_only else protected(path, rules))

    reason = ("a test packet changes only tests; it also changes " if tests_only
              else "implementation changes protected tests or harness: ")
    base = worker.get("base_commit")
    if not base:
        raise ValueError("worker has no pinned baseline; return it for a fresh assignment")
    head = git.head(repo, worker["branch"])
    if not git.contains(repo, base, head):
        raise ValueError("worker branch does not contain its pinned baseline")
    for commit in git.run(repo, "rev-list", f"{base}..{head}", "--not", main).splitlines():
        inherited = git.run(repo, "merge-base", main, commit)
        paths = [p for p in git.changed(repo, inherited, commit) if forbidden(p)]
        if paths:
            raise ValueError(reason + ", ".join(paths))


def incorporated(repo, worker, commit, rules) -> None:
    """Main holds exactly the production files the worker changed. A rewrite, however
    equivalent, needs an integrator's review and landing: ancestry or a green suite alone cannot
    prove the worker's work was incorporated."""
    head, base = git.head(repo, worker["branch"]), worker["base_commit"]
    stage_history(repo, worker, commit, rules)
    paths = production(repo, base, head, rules)
    if not paths:
        raise ValueError("worker has no production changes to reconcile")
    for path in paths:
        if git.blob(repo, head, path) != git.blob(repo, commit, path):
            raise ValueError("main does not contain the exact submitted behavior: " + path)


def _run(checkout, commit, command, deadline, memory_gb=None) -> tuple[int, str]:
    """One command on a checked-out candidate: (exit code, output tail). Timeout raises."""
    remaining = max(0.01, deadline - time.monotonic())
    unit = "cointos-test-" + secrets.token_hex(6) if memory_gb is not None else None
    run = (["systemd-run", "--user", "--quiet", "--wait", "--pipe", "--collect", f"--unit={unit}",
            f"--working-directory={checkout}", f"--property=MemoryMax={memory_gb}G",
            "--property=MemorySwapMax=0", "--property=OOMPolicy=stop", "--property=KillMode=control-group",
            f"--property=RuntimeMaxSec={remaining}", "--property=TimeoutStopSec=1", "--", *command]
           if unit else command)
    with tempfile.TemporaryFile() as output:
        child = subprocess.Popen(run, cwd=checkout, stdout=output, stderr=output, start_new_session=True)
        try:
            code = child.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
            raise ValueError(f"test command timed out: {command}")
        finally:
            if unit:
                subprocess.run(["systemctl", "--user", "stop", unit], capture_output=True,
                               timeout=max(1.0, remaining), check=False)
        output.seek(max(0, output.tell() - OUTPUT_LIMIT))
        text = output.read().decode(errors="replace")
    if git.run(checkout, "diff", "HEAD", "--name-only") or git.head(checkout) != commit:
        raise ValueError("test command changed the checked-out candidate")
    return code, text


@contextlib.contextmanager
def checkout(repo, commit: str):
    """A fresh detached worktree of the exact commit, removed afterwards."""
    with tempfile.TemporaryDirectory(prefix="cointos-check-") as temp:
        path = Path(temp) / "candidate"
        git.run(repo, "worktree", "add", "--detach", str(path), commit)
        try:
            yield path
        finally:
            git.run(repo, "worktree", "remove", "--force", str(path))


def registered(repo, commit: str, rules: dict) -> list[list[str]]:
    """Every test command a commit's manifest registers (none without a manifest)."""
    if git.blob(repo, commit, rules["manifest"]) is None:
        return []
    return [c["command"] for c in contracts(repo, commit, rules)]


def packet_tests(repo, main: str, tests: list[str], rules: dict) -> list[list[str]]:
    """A packet's own tests: the commands its test commits register beyond main's."""
    accepted, own = registered(repo, main, rules), []
    for commit in tests:
        own += [c for c in registered(repo, commit, rules) if c not in accepted and c not in own]
    return own


def packet_files(repo, main: str, tests: list[str], rules: dict) -> list[str]:
    """The protected files a packet's test commits write."""
    found = []
    for commit in tests:
        base = git.run(repo, "merge-base", main, commit)
        found += [p for p in git.changed(repo, base, commit) if protected(p, rules) and p not in found]
    return found


@contextlib.contextmanager
def combined(repo, commit: str, tests: list[str]):
    """A fresh detached checkout of `commit` with a packet's test commits merged in: (path, head)."""
    with checkout(repo, commit) as path:
        for test in tests:
            merged = git.result(path, "-c", "user.name=CointOS", "-c", "user.email=cointos@localhost",
                                "merge", "-q", "--no-edit", test)
            if merged.returncode:
                git.result(path, "merge", "--abort")
                raise ValueError(f"the packet's tests ({test[:12]}) do not merge with {commit[:12]}:\n"
                                 + (merged.stdout + merged.stderr).strip()[-2000:])
        yield path, git.head(path)


LOCATIONS = (re.compile(r'File "([^"]+)", line (\d+)'), re.compile(r"([\w./-]+\.\w+):(\d+)"))


def reveal(path, output: str, files: list[str], context: int = 12, limit: int = 6) -> str:
    """The test source around each failure location the output names in the given files, or the
    files themselves when it names none."""
    root, shown, parts = str(path).rstrip("/") + "/", set(), []
    for pattern in LOCATIONS:
        for name, number in pattern.findall(output):
            name = name[len(root):] if name.startswith(root) else name
            match = next((f for f in files if f == name or f.endswith("/" + name)), None)
            if match is None or (match, number) in shown or len(parts) >= limit:
                continue
            shown.add((match, number))
            lines = (Path(path) / match).read_text(errors="replace").splitlines()
            line = int(number)
            low, high = max(1, line - context), min(len(lines), line + context)
            parts.append(f"{match}:{low}-{high}\n" + "\n".join(f"{n:6} {lines[n - 1]}" for n in range(low, high + 1)))
    if not parts:
        for name in files:
            if (Path(path) / name).is_file():
                parts.append(f"{name}\n" + (Path(path) / name).read_text(errors="replace")[:6000])
    return "\n\n".join(parts)


def failures(path, results: list[tuple[list[str], str]], files: list[str]) -> str:
    """Failing tests as an implementer sees them: command, output tail and revealed source."""
    return "\n\n".join(f"Failing test: {' '.join(command)}\n{output[-3000:]}\n\nTest source:\n"
                        f"{reveal(path, output, files)}" for command, output in results)


def packet_check(repo, main: str, commit: str, tests: list[str], bundled: list[list[str]], rules: dict,
                 timeout: float, memory_gb=None) -> dict:
    """Run a packet's own tests (and any bundled in by its integrator) against its code; a
    ValueError reveals each failing test."""
    own = packet_tests(repo, main, tests, rules)
    own += [list(c) for c in bundled if list(c) not in own]
    deadline = time.monotonic() + timeout
    with combined(repo, commit, tests) as (path, head):
        failed = []
        for command in own:
            code, output = _run(path, head, command, deadline, memory_gb)
            if code:
                failed.append((command, output))
        if failed:
            raise ValueError(f"{len(failed)} of the packet's {len(own)} tests fail. They are shown here; the rest "
                             f"stay hidden. Fix the code (not the tests), commit, then finish again.\n\n"
                             + failures(path, failed, packet_files(repo, main, tests, rules)
                                        + [c for c in bundled_files(path, failed)]))
    return {"tests": list(tests), "packet_tests": len(own)}


def passing(repo, main: str, tests: list[str], rules: dict, timeout: float, memory_gb=None) -> bool:
    """Whether a packet's tests already pass on main: main with them merged in passes every
    registered command. Such tests have no code left to wait for."""
    deadline = time.monotonic() + timeout
    try:
        with combined(repo, main, tests) as (path, head):
            return all(_run(path, head, command, deadline, memory_gb)[0] == 0
                       for command in registered(repo, head, rules))
    except ValueError:  # they do not merge with main, or a command timed out
        return False


def bundled_files(path, failed) -> list[str]:
    """Test files a failing command's output names, for tests bundled in from the full suite."""
    found = []
    for _, output in failed:
        for pattern in LOCATIONS:
            for name, _ in pattern.findall(output):
                name = name[len(str(path)) + 1:] if name.startswith(str(path)) else name
                if (Path(path) / name).is_file() and name not in found:
                    found.append(name)
    return found


def packet_unchanged(repo, worker: dict, main: str, candidate: str, tests: list[str], rules: dict) -> None:
    """Stage ownership holds and the complete test tree equals main plus the packet.
    A test writer supplies its own commit; an implementer supplies its accepted test commits."""
    stage_history(repo, worker, main, rules)
    with combined(repo, main, tests) as (_, expected):
        changed = [p for p in git.changed(repo, expected, candidate) if protected(p, rules)]
        if changed:
            raise ValueError("candidate tests differ from main plus the accepted packet: " + ", ".join(changed))


def tests_landed(repo, main: str, tests: list[str], rules: dict) -> bool:
    """Whether main already holds a packet's tests exactly as written."""
    files = packet_files(repo, main, tests, rules)
    if not files:
        return True
    with combined(repo, main, tests) as (_, merged):
        return all(git.blob(repo, merged, name) == git.blob(repo, main, name) for name in files)


def suite(repo, main: str, candidate: str, rules: dict, timeout: float, memory_gb=None) -> tuple[dict, list]:
    """The full suite on a landing candidate: every registered command. Returns its counts and
    the failures the candidate causes (red on the candidate, not red on main), each as
    (command, output, revealed source). A failure main already has is not the packet's."""
    commands = registered(repo, candidate, rules)
    on_main = registered(repo, main, rules)
    deadline = time.monotonic() + timeout
    with checkout(repo, candidate) as path:
        red = [(c, out) for c in commands for code, out in [_run(path, candidate, c, deadline, memory_gb)] if code]
        caused = []
        if red:
            with checkout(repo, main) as before:
                already = [c for c, _ in red if c in on_main and _run(before, main, c, deadline, memory_gb)[0]]
            caused = [(c, out, reveal(path, out, bundled_files(path, [(c, out)])))
                      for c, out in red if c not in already]
    return {"suite": len(commands), "red_on_main": len(red) - len(caused)}, caused
