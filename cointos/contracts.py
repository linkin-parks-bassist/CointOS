"""Implementation test contracts: what a landing must preserve and which accepted checks it must pass.

A project's test policy names its contract manifest (a JSON list of {"covers", "command"}),
the protected test paths and the non-code paths. The landing gate (`cointos/landing.py`) uses
these functions to decide which commands a candidate commit must pass, then `verify` runs them
on a fresh checkout of that exact commit.
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


def affected(repo, before, after, rules, *, inherit_private=False) -> set[str]:
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
        # Private helpers inherit the contracts of all reachable public callers.
        # Unreferenced helpers (including isolated recursive cycles) still need coverage.
        if inherit_private:
            impacted = {n for n in impacted if not n.startswith("_") or
                        not any(u != n and u and not u.startswith("_") for u in users({n}))}
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


def covers(pattern: str, target: str) -> bool:
    path, _, symbol = target.partition("::")
    wanted, sep, name = pattern.partition("::")
    return fnmatch.fnmatchcase(path, wanted) and (not sep or not symbol or fnmatch.fnmatchcase(symbol, name))


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


def implementation_checks(repo, worker, main, candidate, rules) -> list[list[str]]:
    implementation_history(repo, worker, main, rules)
    check_test_diff(repo, main, candidate, rules)  # includes integrator edits/conflict resolutions
    return affected_checks(repo, main, candidate, main, rules)


def affected_checks(repo, before, candidate, contracts_at, rules) -> list[list[str]]:
    targets = affected(repo, before, candidate, rules)
    registered = contracts(repo, contracts_at, rules) if targets else []
    required = affected(repo, before, candidate, rules, inherit_private=True)
    missing = [t for t in sorted(required) if not any(covers(p, t) for c in registered for p in c["covers"])]
    if missing:
        raise ValueError("changed code has no accepted test contract: " + ", ".join(missing))
    selected = [c["command"] for c in registered if any(covers(p, t) for p in c["covers"] for t in targets)]
    return [list(command) for command in dict.fromkeys(tuple(c) for c in selected)]


def integration_tests(repo, main, candidate, rules):
    """Integration may add contracts, never weaken the already accepted ones."""
    for path in git.changed(repo, main, candidate):
        if protected(path, rules) and path != rules["manifest"] and git.blob(repo, main, path) is not None:
            raise ValueError("integration changes existing protected tests: " + path)
    added = []
    if rules["manifest"] in git.changed(repo, main, candidate):
        accepted = contracts(repo, main, rules)
        proposed = contracts(repo, candidate, rules)
        if any(c not in proposed for c in accepted):
            raise ValueError("integration removes or changes accepted contracts")
        added = [c["command"] for c in proposed if c not in accepted]
    return added


def incorporated(repo, worker, commit, rules) -> list[list[str]]:
    """Exact changed definitions/files must exist on main, with its accepted checks green.

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
    return affected_checks(repo, base, head, commit, rules)


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


EXPECTED_RED = re.compile(r"\**Expected red:\**\s*(.*)", re.IGNORECASE)


def expected_reds(report: str) -> list[tuple[list[str], str]]:
    """A test-contract report's declared red checks, `Expected red: COMMAND => OUTPUT LITERAL`
    lines outside fenced code; `Expected red: none` declares that every new check is green."""
    found, fence, declared = [], None, False
    for line in report.splitlines():
        stripped = line.strip().lstrip("-*").strip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            fence = None if fence == marker else marker if fence is None else fence
            continue
        match = EXPECTED_RED.fullmatch(stripped) if fence is None else None
        if not match:
            continue
        declared = True
        value = match.group(1).strip().strip("`").strip()
        if value.lower() == "none":
            continue
        command, sep, literal = value.partition("=>")
        command, literal = shlex.split(command.strip().strip("`")) if sep else [], literal.strip().strip("`").strip()
        if not command or not literal:
            raise ValueError(f"malformed expected red (want `Expected red: COMMAND => OUTPUT LITERAL`): {line.strip()}")
        found.append((command, literal))
    if not declared:
        raise ValueError("test-contract report declares no `Expected red: COMMAND => OUTPUT LITERAL` "
                         "line (or `Expected red: none`)")
    return found


def red_gate(repo, parent: str, commit: str, report: str, rules: dict, timeout: float, memory_gb=None) -> dict:
    """Mechanically check a test-contract candidate's claims: every declared red check fails on
    the candidate with its declared output, and no other contract green on main turns red.

    Candidate results come first; main is only consulted for contracts red on the candidate,
    so the common all-green case runs each command once."""
    expected = expected_reds(report)
    accepted = contracts(repo, parent, rules) if git.show(repo, parent, rules["manifest"]) else []
    commands = list(dict.fromkeys(tuple(c["command"]) for c in accepted))
    deadline = time.monotonic() + timeout
    results: dict[tuple, tuple[int, str]] = {}
    with checkout(repo, commit) as path:
        for command in commands + [tuple(c) for c, _ in expected if tuple(c) not in commands]:
            results[command] = _run(path, commit, list(command), deadline, memory_gb)
    for command, literal in expected:
        code, text = results[tuple(command)]
        if not code:
            raise ValueError(f"declared red check passes on the candidate: {command}")
        if literal not in text:
            raise ValueError(f"declared red check {command} failed ({code}) without its declared output "
                             f"{literal!r}; actual output tail:\n" + text[-4000:])
    # A declared red is checked by its literal; an accepted target may legitimately turn red
    # when the new deliberate failure is appended to it.
    declared = {tuple(c) for c, _ in expected}
    red = [c for c in commands if results[c][0] and c not in declared]
    regressed = []
    if red:
        with checkout(repo, parent) as path:
            for command in red:
                if not _run(path, parent, list(command), deadline, memory_gb)[0]:
                    regressed.append(command)
    if regressed:
        details = "\n".join(f"{list(c)}:\n{results[c][1][-2000:]}" for c in regressed)
        raise ValueError("test contract turns accepted green checks red: " + details)
    return {"expected_red": len(expected), "contracts_run": len(commands), "red_on_main": len(red)}
