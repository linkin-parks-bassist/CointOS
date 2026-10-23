"""Test packets: the tests a piece of code travels with, and the suite it must not break.

A project's test policy names its contract manifest (a JSON list of {"covers", "command"}),
the protected test paths and the non-code paths. A test writer's commit registers a packet's
tests. Every completed packet requires integrator review. Tests already passing on main
land after review; reviewed failing ones stay off main,
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
import sys
import tempfile
import time

from cointos import config as configuration, git, trees

OUTPUT_LIMIT = 1 << 20  # output tail kept for red-check literals and failure details
TIMEOUTS = configuration.load()['timeouts']


class ExecutionError(ValueError):
    """Validation did not produce assertion evidence; it cannot reject product code."""


def matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def protected(path: str, rules: dict) -> bool:
    return path == rules["manifest"] or matches(path, rules.get("protected", []))


def production(repo, before, after, rules) -> list[str]:
    """Production changes in a commit, or the working tree when after is None."""
    paths = git.changed(repo, before, after) if after is not None else working_paths(repo, before)
    return sorted({p for p in paths
                   if not protected(p, rules) and not matches(p, rules.get("non_code", []))})


def working_paths(repo, before='HEAD') -> list[str]:
    """Tracked edits/deletions and untracked files, without changing the checkout."""
    return sorted({p for p in (git.run(repo, 'diff', '--no-renames', '--name-only', '-z', before) +
                              git.run(repo, 'ls-files', '--others', '--exclude-standard', '-z')).split('\0') if p})


def working_stage_changes(repo, stage, rules) -> list[str]:
    """Uncommitted files outside the worker stage's ownership."""
    return [p for p in working_paths(repo)
            if ((not protected(p, rules) and not matches(p, rules.get('non_code', [])))
                if stage == 'test-contract' else protected(p, rules))]


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


def worker_artifact(repo, task, commit):
    """Construction completion needs a changed artifact, not an inspection receipt."""
    base = task.get('base_commit')
    if not base:
        raise ValueError('worker has no pinned baseline; return it for a fresh assignment')
    paths = [p for p in git.changed(repo, base, commit) if p != '.work-report.md']
    if not paths:
        raise ValueError('construction work has no changed artifact relative to its assigned baseline; '
                         'continue the scoped work or finish blocked if this is only inspection/status. '
                         'Inspection and status belong to planning or an assigned Operator, not code integration.')


def maintenance_history(where, task, main, *, include_worktree=False):
    """Maintenance cannot replace independently reviewed project construction.

    Check unpublished history, including reverted diagnostics; preflight also
    checks staged, unstaged and untracked changes when include_worktree is set. System Operators
    retain their separately assigned infrastructure scope outside managed products.
    """
    if task['role'] == 'operator' and task['place'] == 'system':
        return
    repo, rules = where['path'], where.get('test_policy')
    tree = Path(where.get('tree', '.knowledge'))
    if tree.is_absolute():
        tree = tree.resolve().relative_to(Path(repo).resolve())
    prefix = '' if tree == Path('.') else tree.as_posix().rstrip('/') + '/'

    def allowed(path):
        if rules and protected(path, rules):
            return False
        if path.startswith(prefix) and path.endswith('.md'):
            return True
        return task['role'] == 'operator' and rules and matches(path, rules.get('non_code', []))

    head = git.head(repo, task['branch'])
    for commit in git.run(repo, 'rev-list', f'{main}..{head}').splitlines():
        inherited = git.run(repo, 'merge-base', main, commit)
        paths = [p for p in git.changed(repo, inherited, commit) if not allowed(p)]
        if paths:
            scope = ('manager planning may publish only knowledge-tree changes' if task['role'] == 'manager'
                     else 'maintenance may publish only knowledge or configured non-code changes')
            raise ValueError(scope + '; preserve product code and protected tests for a worker and independent review: '
                             + ', '.join(paths))
    if include_worktree:
        paths = [p for p in working_paths(task['worktree']) if not allowed(p)]
        if paths:
            raise ValueError('uncommitted maintenance changes require a worker and independent review: '
                             + ', '.join(paths) + '; preserve these artifacts for their construction owner, '
                             'not maintenance publication')
    changed = git.changed(repo, main, head)
    if include_worktree:
        changed += working_paths(task['worktree'])
    knowledge = [p for p in changed if p.startswith(prefix) and p.endswith('.md')]
    conflicts = trees.answer_edits(repo, knowledge)
    if conflicts:
        raise ValueError('maintenance overlaps pending canonical knowledge answers or policy: ' + ', '.join(conflicts) +
                         '; this guard compares canonical working files and index with their checkout HEAD. '
                         'It does not identify a queue owner. Preserve the pending answers; retry publication '
                         'only after authorized reconciliation, or finish blocked.')


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
    # Hardcoded host /tmp outputs have one CointOS writer. The executed process
    # owns the lock, including when its daemon disappears but its unit survives.
    # This lock is distinct from the ledger and repository publication locks.
    configuration.STATE.mkdir(parents=True, exist_ok=True)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ExecutionError(f'validation budget exhausted before test command: {command}')
    unit = "cointos-test-" + secrets.token_hex(6) if memory_gb is not None else None
    with tempfile.TemporaryDirectory(prefix='cointos-execution-') as directory, tempfile.TemporaryFile() as output:
        report = Path(directory) / 'result.json'
        execute = [sys.executable, str(Path(__file__).with_name('validation.py')), str(report),
                   str(TIMEOUTS['command_seconds']), str(deadline), *command]
        locked = ['flock', '--exclusive', '--', str(configuration.STATE / 'test-output.lock'), *execute]
        run = (["systemd-run", "--user", "--quiet", "--wait", "--pipe", "--collect", f"--unit={unit}",
                f"--working-directory={checkout}", f"--property=MemoryMax={memory_gb}G",
                "--property=MemorySwapMax=0", "--property=OOMPolicy=stop", "--property=KillMode=control-group",
                f"--property=RuntimeMaxSec={remaining}", "--property=TimeoutStopSec=1", "--", *locked]
               if unit else locked)
        child = subprocess.Popen(run, cwd=checkout, stdout=output, stderr=output, start_new_session=True)
        try:
            child.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
            raise ExecutionError(f'validation budget timed out during test command or output-lease wait: {command}')
        finally:
            if unit:
                subprocess.run(["systemctl", "--user", "stop", unit], capture_output=True,
                               timeout=5, check=False)
            else:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        output.seek(max(0, output.tell() - OUTPUT_LIMIT))
        text = output.read().decode(errors="replace")
        try:
            result = json.loads(report.read_text())
        except (OSError, ValueError) as error:
            raise ExecutionError(f'test execution ended without a result: {command}\n{text[-3000:]}') from error
        if result.get('timeout'):
            raise ExecutionError(f"{result['timeout']} budget timed out: {command}\n{text[-3000:]}")
        if child.returncode:
            raise ExecutionError(f'test execution unit failed (exit {child.returncode}): {command}\n{text[-3000:]}')
        if result.get('error') or not isinstance(result.get('code'), int):
            raise ExecutionError(f'test command could not execute: {command}: {result}')
        code = result['code']
        if code < 0:
            raise ExecutionError(f'test command terminated by signal {-code}: {command}\n{text[-3000:]}')
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
    """New packet commands, or the suite for changed/shared harnesses and reused commands.

    Command identity alone cannot identify changed assertions inside a shared target.
    The manifest maps production coverage, not test-file ownership, so use the suite
    rather than guessing a command from a filename. A reused command never means no tests.
    """
    accepted, own = registered(repo, main, rules), []
    for commit in tests:
        commands = registered(repo, commit, rules)
        added = [c for c in commands if c not in accepted]
        base = git.run(repo, 'merge-base', main, commit)
        shared = any(path != rules['manifest'] and protected(path, rules)
                     and git.blob(repo, base, path) is not None
                     for path in git.changed(repo, base, commit))
        # Explicit registration of a reused command also makes it part of this packet,
        # even alongside a genuinely new command. Compare entries with multiplicity.
        before = list(contracts(repo, base, rules)) if git.blob(repo, base, rules['manifest']) is not None else []
        reused = False
        for entry in contracts(repo, commit, rules):
            if entry in before:
                before.remove(entry)
            elif entry['command'] in accepted:
                reused = True
        selected = commands if shared or reused or not added else added
        for command in selected:
            if command not in own:
                own.append(command)
    return own


def packet_files(repo, main: str, tests: list[str], rules: dict) -> list[str]:
    """The protected files a packet's test commits write."""
    found = []
    for commit in tests:
        base = git.run(repo, "merge-base", main, commit)
        found += [p for p in git.changed(repo, base, commit) if protected(p, rules) and p not in found]
    return found


@contextlib.contextmanager
def combined(repo, commit: str, tests: list[str], rules: dict):
    """A fresh detached checkout of `commit` with a packet's test commits merged in: (path, head)."""
    with checkout(repo, commit) as path:
        for test in tests:
            merged = git.result(path, "-c", "user.name=CointOS", "-c", "user.email=cointos@localhost",
                                "merge", "-q", "--no-edit", test)
            if merged.returncode:
                conflicts = git.run(path, "diff", "--name-only", "--diff-filter=U", "-z").split("\0")
                git.resolve_insertions(path, [p for p in conflicts if p and protected(p, rules)])
                if any(conflicts) and not git.run(path, "ls-files", "-u"):
                    git.run(path, "-c", "user.name=CointOS", "-c", "user.email=cointos@localhost",
                            "commit", "-q", "--no-edit")
                    continue
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
    with combined(repo, commit, tests, rules) as (path, head):
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
        with combined(repo, main, tests, rules) as (path, head):
            return all(_run(path, head, command, deadline, memory_gb)[0] == 0
                       for command in registered(repo, head, rules))
    except ExecutionError:
        raise
    except ValueError:  # packet composition does not establish a passing artifact
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


def packet_unchanged(repo, worker: dict, main: str, candidate: str | None, tests: list[str], rules: dict) -> None:
    """Stage ownership holds and the complete test tree equals main plus the packet.
    A test writer supplies its own commit; an implementer supplies its accepted test commits."""
    stage_history(repo, worker, main, rules)
    with combined(repo, main, tests, rules) as (_, expected):
        paths = git.changed(repo, expected, candidate) if candidate is not None else working_paths(repo, expected)
        changed = [p for p in paths if protected(p, rules)]
        if changed:
            comparison = f'git diff {expected} {candidate} --' if candidate is not None else f'git diff {expected} --'
            raise ValueError("candidate tests differ from main plus the accepted packet: " + ", ".join(changed)
                             + f". Compare the required protected tree with your candidate using "
                             f"{comparison}. Protected paths include configured "
                             "harness/build files, not only test source. This is a candidate-content "
                             "mismatch, not a stage mismatch. Preserve main plus the submitted packet; "
                             "return defective packet changes to the worker instead of editing them "
                             "in review. Changing the stage does not repair this mismatch.")


def tests_landed(repo, main: str, tests: list[str], rules: dict) -> bool:
    """Whether main already holds a packet's tests exactly as written."""
    files = packet_files(repo, main, tests, rules)
    if not files:
        return True
    with combined(repo, main, tests, rules) as (_, merged):
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
    return {"suite": len(commands), "failed": len(red), "red_on_main": len(red) - len(caused)}, caused
