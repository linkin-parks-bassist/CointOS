"""Test packets: the tests a piece of code travels with, and the suite it must not break.

A project's test policy names its contract manifest (a JSON list of {"covers", "command"}),
the protected test paths and the non-code paths. A test writer's commit registers a packet's
tests; they stay off main, hidden from the implementer, until they land with the code that
passes them. `packet_check` runs them when the implementer finishes; `suite` runs every
registered command on a landing candidate; `verify` runs commands on a fresh checkout.
"""
from __future__ import annotations

import ast
import contextlib
import fnmatch
import json
import os
import re
import shlex
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


def check_test_diff(repo, before, after, rules):
    touched = [p for p in git.changed(repo, before, after) if protected(p, rules)]
    if touched:
        raise ValueError("implementation changes protected tests or harness: " + ", ".join(touched))


def symbols(source: str) -> tuple[dict, dict, dict, str]:
    """Index top-level definitions and named imports; retain executable module code."""
    tree = ast.parse(source)
    found, imports, references, module = {}, {}, {}, []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found[node.name] = ast.dump(node, include_attributes=False)
            references[node.name] = {n.id for n in ast.walk(node)
                                     if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        elif isinstance(node, (ast.Import, ast.ImportFrom)) and not (
                isinstance(node, ast.ImportFrom) and (node.module == "__future__" or
                                                     any(a.name == "*" for a in node.names))):
            for alias in node.names:
                name = alias.asname or (alias.name.split(".")[0] if isinstance(node, ast.Import) else alias.name)
                # Keep repeated bindings and import order visible.
                imports.setdefault(name, []).append((type(node).__name__, getattr(node, "module", None),
                                                      getattr(node, "level", 0), alias.name, alias.asname))
        else:
            module.append(node)
    references[""] = {n.id for node in module for n in ast.walk(node)
                      if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    return found, imports, references, repr([ast.dump(n, include_attributes=False) for n in module])


def affected(repo, before, after, rules) -> set[str]:
    targets = set()
    for path in git.changed(repo, before, after):
        if protected(path, rules) or matches(path, rules.get("non_code", [])):
            continue
        if not path.endswith(".py"):
            targets.add(path)
            continue
        versions = []
        for rev in (before, after):
            try:
                versions.append(symbols(git.show(repo, rev, path)))
            except SyntaxError:
                versions.append(None)
        old, new = versions
        if old is None or new is None or old[3] != new[3]:
            targets.add(path)
            continue
        definitions = old[0].keys() | new[0].keys()
        changed_names = {n for n in definitions if old[0].get(n) != new[0].get(n)}
        changed_imports = {n for n in old[1].keys() | new[1].keys() if old[1].get(n) != new[1].get(n)}
        references = {n: old[2].get(n, set()) | new[2].get(n, set()) for n in definitions | {""}}

        def users(names):
            reached = set(names)
            while True:
                expanded = reached | {n for n, refs in references.items() if refs & reached}
                if expanded == reached:
                    return reached
                reached = expanded

        impacted = users(changed_names | changed_imports)
        # Import side effects, wildcard/future imports and executable module edits
        # cannot safely be assigned to one function. Unused imports stay conservative.
        if "" in impacted or any(not (users({n}) & definitions) for n in changed_imports):
            targets.add(path)
            continue
        impacted &= definitions
        targets.update(f"{path}::{name}" for name in impacted)
    return targets


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


def implementation_history(repo, worker, main, rules):
    base = worker.get("base_commit")
    if not base:
        raise ValueError("implementation has no pinned test baseline; return it for a fresh assignment")
    head = git.head(repo, worker["branch"])
    if not git.contains(repo, base, head):
        raise ValueError("implementation branch does not contain its pinned test baseline")
    # Even a test edit subsequently reverted is not an implementation commit.
    for commit in git.run(repo, "rev-list", f"{base}..{head}", "--not", main).splitlines():
        parents = git.run(repo, "rev-list", "--parents", "-n", "1", commit).split()[1:]
        if len(parents) == 1:
            check_test_diff(repo, parents[0], commit, rules)
        else:
            # Bringing accepted tests from main is legal; inventing protected merge
            # resolutions is not. Final candidate must still preserve current main.
            paths = {p for parent in parents for p in git.changed(repo, parent, commit) if protected(p, rules)}
            for path in paths:
                blob = git.blob(repo, commit, path)
                if not any(blob == git.blob(repo, parent, path) for parent in parents):
                    raise ValueError("implementation merge changes protected tests: " + path)


def incorporated(repo, worker, commit, rules) -> None:
    """Exact changed definitions/files must exist on main.

    This intentionally refuses semantic rewrites: an integrator must review those.
    Ancestry or a green suite alone cannot prove the worker's work was incorporated.
    """
    head, base = git.head(repo, worker["branch"]), worker["base_commit"]
    implementation_history(repo, worker, commit, rules)
    targets = affected(repo, base, head, rules)
    if not targets:
        raise ValueError("worker has no production changes to reconcile")
    for path in sorted({t.partition("::")[0] for t in targets}):
        equal = git.blob(repo, head, path) == git.blob(repo, commit, path)
        if not equal and path.endswith(".py"):
            versions = []
            for revision in (base, head, commit):
                source = git.show(repo, revision, path)
                tree = ast.parse(source)
                # Documentation refreshes are not changed executable behavior.
                for node in ast.walk(tree):
                    body = getattr(node, "body", None)
                    if (isinstance(body, list) and body and isinstance(body[0], ast.Expr)
                            and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str)):
                        body.pop(0)
                versions.append(symbols(ast.unparse(tree)))
            before, submitted, landed = versions
            names = {n for n in before[0].keys() | submitted[0].keys() if before[0].get(n) != submitted[0].get(n)}
            while True:
                expanded = names | {n for name in names for n in submitted[2].get(name, set()) if n in submitted[0]}
                if expanded == names:
                    break
                names = expanded
            bindings = {n for n in before[1].keys() | submitted[1].keys() if before[1].get(n) != submitted[1].get(n)}
            # Keep the imported environment of changed definitions stable too.
            bindings |= {n for name in names for n in submitted[2].get(name, set()) if n in submitted[1]}
            equal = (all(submitted[0].get(n) == landed[0].get(n) for n in names)
                     and all(submitted[1].get(n) == landed[1].get(n) for n in bindings)
                     and submitted[3] == landed[3])
        if not equal:
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


def verify(repo, commit: str, commands: list[list[str]], timeout: float, memory_gb=None) -> None:
    """Run the accepted checks on a fresh detached checkout of the exact candidate."""
    deadline = time.monotonic() + timeout
    with checkout(repo, commit) as path:
        for command in commands:
            code, text = _run(path, commit, command, deadline, memory_gb)
            if code:
                raise ValueError(f"test command failed ({code}): {command}\n" + text[-8000:])


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
    """The implementer never touched tests, and the candidate's tests are exactly main's plus the
    packet's: no integrator edit or conflict resolution changes them."""
    implementation_history(repo, worker, main, rules)
    changed = [p for p in git.changed(repo, main, candidate) if protected(p, rules)]
    if not changed:
        return
    def blob(commit, name):
        found = git.result(repo, "rev-parse", "--verify", "--quiet", f"{commit}:{name}")
        return found.stdout.strip() if found.returncode == 0 else None

    with combined(repo, main, tests) as (_, expected):
        for name in changed:
            if blob(candidate, name) != blob(expected, name):
                raise ValueError("the candidate changes tests beyond the packet's own: " + name)


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
