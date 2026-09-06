"""Explicit leases for user-driven agent sessions (R8).

Ordinary management honours active sessions; only the Coin reserve path may
preempt one, and only with evidence. A dead session has no self-healing path;
clearing it is a separate operator concern (see 0008 and 0009).
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

from survival import records

from ecosystem import inference_capacity


STATE_VERSION = 1
STATE_NAME = "operator-sessions.json"
LOCK_NAME = "operator-sessions.lock"
REQUIRED_REQUEST_FIELDS = frozenset((
    "session_id", "owner_identity", "tool", "model_id", "request_id",
))
PREEMPTION_OUTCOME = {"state": "preempted", "returncode": None}


def acquire_operator_session(
    root: Path,
    request: dict,
    clock: Callable[[], float],
) -> dict:
    validated = _validate_request(request)
    values = inference_capacity.scheduling_snapshot(root)
    if "user_driven" not in values["priority_bands"]:
        raise ValueError("scheduling policy has no user_driven band")
    now = _now(clock)
    with _locked_state(root) as (state, save):
        prior = _session_for_request(state, validated["request_id"])
        if prior is not None:
            if prior["request"] != validated:
                raise ValueError("operator session request identity mismatch")
            return prior.copy()
        session = {
            "session_id": validated["session_id"],
            "state": "starting",
            "request": validated,
            "acquired_monotonic": now,
            "process": None,
            "release_outcome": None,
            "released_monotonic": None,
            "reconciliation": None,
        }
        state["sessions"][validated["session_id"]] = session
        save()
        return session.copy()


def register_operator_process(
    root: Path,
    session_id: str,
    pid: int,
    process_start_ticks: int,
    clock: Callable[[], float],
) -> dict:
    if type(pid) is not int or pid <= 0:
        raise ValueError("invalid session process pid")
    if type(process_start_ticks) is not int or process_start_ticks < 0:
        raise ValueError("invalid session process start identity")
    now = _now(clock)
    with _locked_state(root) as (state, save):
        session = _session(state, session_id)
        identity = {"pid": pid, "process_start_ticks": process_start_ticks}
        if session["state"] == "active":
            if session["process"] != identity:
                raise ValueError("session process identity mismatch")
            return session.copy()
        if session["state"] != "starting":
            raise ValueError("session process registration is no longer admissible")
        session["process"] = identity
        session["state"] = "active"
        session["registered_monotonic"] = now
        save()
        return session.copy()


def release_operator_session(
    root: Path,
    session_id: str,
    outcome: dict,
    clock: Callable[[], float],
) -> dict:
    validated_outcome = _validate_outcome(outcome)
    now = _now(clock)
    with _locked_state(root) as (state, save):
        session = _session(state, session_id)
        if session["release_outcome"] is not None:
            if session["release_outcome"] != validated_outcome:
                raise ValueError("session release outcome mismatch")
            return session.copy()
        if session["state"] == "dead_unreconciled":
            raise ValueError("dead session requires reconciliation, not release")
        session["release_outcome"] = validated_outcome
        session["release_requested_monotonic"] = now
        session["state"] = "release_requested"
        save()
        return session.copy()


def observe_operator_sessions(
    root: Path,
    observed_sessions: list[dict],
    clock: Callable[[], float],
) -> dict:
    observations = _validate_observations(observed_sessions)
    now = _now(clock)
    with _locked_state(root) as (state, save):
        for observed in observations:
            session = _session(state, observed["session_id"])
            if session["process"] != {
                "pid": observed["pid"],
                "process_start_ticks": observed["process_start_ticks"],
            }:
                raise ValueError("session observation process identity mismatch")
            if observed["process_group_alive"]:
                continue
            if session["state"] == "release_requested":
                session["state"] = "quiescent"
                session["quiescent_monotonic"] = now
            elif session["state"] == "active":
                session["state"] = "dead_unreconciled"
                session["dead_monotonic"] = now
        save()
        return _public_state(state)


def reconcile_operator_session(
    root: Path,
    session_id: str,
    evidence: dict,
    clock: Callable[[], float],
) -> dict:
    validated_evidence = _validate_evidence(evidence)
    now = _now(clock)
    with _locked_state(root) as (state, save):
        session = _session(state, session_id)
        if session["state"] == "quiescent":
            if session["reconciliation"] != validated_evidence:
                raise ValueError("session reconciliation evidence mismatch")
            return session.copy()
        if session["state"] != "dead_unreconciled":
            raise ValueError("session is not awaiting reconciliation")
        session["reconciliation"] = validated_evidence
        session["state"] = "quiescent"
        session["quiescent_monotonic"] = now
        save()
        return session.copy()


def preempt_operator_sessions(
    root: Path,
    evidence: dict,
    clock: Callable[[], float],
) -> list[dict]:
    validated_evidence = _validate_preemption_evidence(evidence)
    now = _now(clock)
    with _locked_state(root) as (state, save):
        preempted = []
        for session in state["sessions"].values():
            if session["state"] != "active":
                continue
            session["release_outcome"] = PREEMPTION_OUTCOME
            session["release_requested_monotonic"] = now
            session["state"] = "release_requested"
            session["preemption"] = {
                **validated_evidence,
                "requested_monotonic": now,
            }
            preempted.append(session.copy())
        if preempted:
            save()
        return preempted


def active_operator_sessions(root: Path) -> list[dict]:
    with _locked_state(root) as (state, _save):
        return [
            session.copy()
            for session in state["sessions"].values()
            if session["state"] == "active"
        ]


def operator_session_owns_model(root: Path, model_name: str) -> str | None:
    if type(model_name) is not str or not model_name:
        raise ValueError("invalid model name")
    with _locked_state(root) as (state, _save):
        for session in state["sessions"].values():
            if session["state"] != "active":
                continue
            pinned = session["request"]["model_id"]
            if pinned is not None and pinned == model_name:
                return session["session_id"]
    return None


def run_command(
    root: Path,
    request: dict,
    command: list[str],
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """Acquire, spawn the operator tool blocked in its own process group,
    register it before it may exec, wait for it, release the session with the
    child's outcome, and return the exit code. Only a fresh starting session
    may spawn; a stale or dead session must be reconciled or released before
    the tool is launched again."""
    session = acquire_operator_session(root, request, clock)
    if session["state"] != "starting":
        raise ValueError(
            f"operator session {session['session_id']} is not fresh "
            f"(state: {session['state']}); release or reconcile it first")
    # Local import: executor imports resource_control, which imports this
    # module; the gated spawner is only needed at launch time.
    from ecosystem import executor
    gate = executor.gated_child_launch(None, command, dict(os.environ))
    try:
        register_operator_process(
            root, session["session_id"],
            gate["pid"], gate["start_ticks"], clock)
        executor.gated_child_release(gate)
    except Exception as error:
        cleanup_error = None
        try:
            cleanup = executor.gated_child_cleanup(gate)
        except Exception as cleanup_failure:
            cleanup_error = cleanup_failure
            cleanup = {
                "state": "reconciliation_required",
                "error_type": type(cleanup_failure).__name__,
            }
        error.launch_failure = {
            "spawned": True,
            "pid": gate["pid"],
            "start_ticks": gate["start_ticks"],
            "pgid": gate["pgid"],
            "cleanup": cleanup,
        }
        if cleanup_error is not None:
            raise error from cleanup_error
        raise
    returncode = gate["process"].wait()
    release_operator_session(
        root, session["session_id"],
        {"state": "run_finished", "returncode": returncode}, clock)
    return returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cointos-opencode",
        description="Run an operator tool under an explicit session lease.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    run = subparsers.add_parser("run", help="acquire, spawn, wait, release")
    run.add_argument("--session-id", required=True)
    run.add_argument("--owner", required=True)
    run.add_argument("--tool", required=True)
    run.add_argument("--model", default=None)
    run.add_argument("--root", required=True)
    run.add_argument("command", nargs=argparse.REMAINDER)
    status = subparsers.add_parser("status", help="show session leases")
    status.add_argument("--root", required=True)
    release = subparsers.add_parser("release", help="release a session")
    release.add_argument("--session-id", required=True)
    release.add_argument("--root", required=True)
    release.add_argument("--state", required=True)
    release.add_argument("--returncode", type=int, required=True)
    args = parser.parse_args(argv)
    root = Path(args.root)
    if args.subcommand == "run":
        argv_tail = args.command
        if argv_tail and argv_tail[0] in {"--", "-"}:
            argv_tail = argv_tail[1:]
        if not argv_tail:
            parser.error("run needs a command")
        request = {
            "session_id": args.session_id,
            "owner_identity": args.owner,
            "tool": args.tool,
            "model_id": args.model,
            "request_id": f"{args.session_id}:{args.tool}",
        }
        return run_command(root, request, argv_tail)
    if args.subcommand == "status":
        document = json.dumps(
            sorted(active_operator_sessions(root),
                   key=lambda session: session["session_id"]),
            indent=2,
        )
        print(document)
        return 0
    release_operator_session(
        root, args.session_id,
        {"state": args.state, "returncode": args.returncode},
        time.monotonic)
    return 0


def _validate_request(request: dict) -> dict:
    if type(request) is not dict or not REQUIRED_REQUEST_FIELDS <= request.keys():
        raise ValueError("invalid operator session request")
    durable = _durable_copy(request)
    for field in ("session_id", "owner_identity", "tool", "request_id"):
        if type(durable[field]) is not str or not durable[field]:
            raise ValueError(f"invalid operator session {field}")
    if not durable["owner_identity"].startswith("operator:"):
        raise ValueError("operator session owner identity must start with operator:")
    if durable["model_id"] is not None and (
            type(durable["model_id"]) is not str or not durable["model_id"]):
        raise ValueError("invalid operator session model_id")
    return durable


def _validate_outcome(outcome: dict) -> dict:
    if type(outcome) is not dict or not outcome:
        raise ValueError("invalid session outcome")
    if (type(outcome.get("state")) is not str or not outcome["state"]
            or ("returncode" not in outcome
                or (outcome["returncode"] is not None
                    and type(outcome["returncode"]) is not int))):
        raise ValueError("invalid session outcome")
    return _durable_copy(outcome)


def _validate_observations(observations: list[dict]) -> list[dict]:
    if type(observations) is not list:
        raise ValueError("invalid session observations")
    validated = []
    for observed in observations:
        if (type(observed) is not dict
                or type(observed.get("session_id")) is not str
                or not observed["session_id"]
                or type(observed.get("pid")) is not int or observed["pid"] <= 0
                or type(observed.get("process_start_ticks")) is not int
                or observed["process_start_ticks"] < 0
                or type(observed.get("process_group_alive")) is not bool):
            raise ValueError("invalid session observation")
        validated.append({
            "session_id": observed["session_id"],
            "pid": observed["pid"],
            "process_start_ticks": observed["process_start_ticks"],
            "process_group_alive": observed["process_group_alive"],
        })
    return validated


def _validate_evidence(evidence: dict) -> dict:
    if type(evidence) is not dict or set(evidence) != {"evidence_id"} \
            or type(evidence["evidence_id"]) is not str \
            or not evidence["evidence_id"]:
        raise ValueError("invalid session reconciliation evidence")
    return {"evidence_id": evidence["evidence_id"]}


def _validate_preemption_evidence(evidence: dict) -> dict:
    if (type(evidence) is not dict
            or evidence.get("kind") != "coin_reserve"
            or type(evidence.get("required_bytes")) is not int
            or evidence["required_bytes"] <= 0
            or type(evidence.get("incident_id")) is not str
            or not evidence["incident_id"]):
        raise ValueError("invalid coin reserve preemption evidence")
    return {
        "kind": "coin_reserve",
        "required_bytes": evidence["required_bytes"],
        "incident_id": evidence["incident_id"],
    }


def _session_for_request(state: dict, request_id: str) -> dict | None:
    for session in state["sessions"].values():
        if session["request"]["request_id"] == request_id:
            return session
    return None


def _session(state: dict, session_id: str) -> dict:
    session = state["sessions"].get(session_id)
    if session is None:
        raise ValueError(f"unknown operator session {session_id}")
    return session


def _public_state(state: dict) -> dict:
    return {
        "schema_version": state["schema_version"],
        "sessions": {
            session_id: session.copy()
            for session_id, session in state["sessions"].items()
        },
    }


def _durable_copy(value) -> dict:
    try:
        return json.loads(json.dumps(value, sort_keys=True))
    except (TypeError, ValueError) as error:
        raise ValueError("session record is not durable JSON") from error


def _now(clock: Callable[[], float]) -> float:
    value = clock()
    if type(value) not in (int, float) or value < 0:
        raise ValueError("invalid monotonic clock")
    return float(value)


@contextmanager
def _locked_state(root: Path):
    state_directory = Path(root) / "state"
    state_directory.mkdir(parents=True, exist_ok=True)
    state_path = state_directory / STATE_NAME
    lock_path = state_directory / LOCK_NAME
    with lock_path.open("a", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        state = _read_state(state_path)
        dirty = False

        def save():
            nonlocal dirty
            dirty = True

        yield state, save
        if dirty:
            records.atomic_json(state_path, state)


def _read_state(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": STATE_VERSION, "sessions": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("invalid operator session state") from error
    if (type(value) is not dict
            or value.get("schema_version") != STATE_VERSION
            or type(value.get("sessions")) is not dict):
        raise ValueError("invalid operator session state")
    for session in value["sessions"].values():
        if (type(session) is not dict
                or session.get("state") not in {
                    "starting", "active", "release_requested",
                    "quiescent", "dead_unreconciled",
                }
                or type(session.get("session_id")) is not str):
            raise ValueError("invalid operator session state")
    return value


if __name__ == "__main__":
    sys.exit(main())
