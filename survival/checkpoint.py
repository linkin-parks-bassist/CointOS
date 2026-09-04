"""Unprivileged observation and publication of durable job checkpoints."""

import json
import math
import os
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from survival import records, telegram_api, time_policy
from survival.json_codec import decode_json_object


CHECKPOINT_REQUEST_FIELDS = frozenset((
    "schema_version", "request_id", "job_ids", "requested_at",
    "boot_id", "deadline_monotonic",
))
CHECKPOINT_RESULT_FIELDS = frozenset((
    "schema_version", "request_id", "job_id", "state", "opencode_session",
))
CHECKPOINT_RESULT_STATES = frozenset((
    "checkpointed", "already_terminal", "unsupported", "deadline_expired",
))
ACTIVE_JOB_STATES = frozenset(("claimed", "reserved", "running", "verifying"))
TERMINAL_JOB_STATES = frozenset(("completed", "failed", "rejected"))
CHECKPOINT_CATALOG_FIELDS = frozenset(("request_directory", "result_directory"))
MAXIMUM_SESSION_LOG_BYTES = 1024 * 1024


def _canonical_request_id(request_id):
    if type(request_id) is not str or not request_id.startswith("telegram-"):
        raise ValueError("invalid checkpoint request identity")
    suffix = request_id.removeprefix("telegram-")
    if not suffix.isdecimal() or f"telegram-{int(suffix)}" != request_id:
        raise ValueError("invalid checkpoint request identity")
    return request_id


def _canonical_job_id(job_id):
    if (
        type(job_id) is not str
        or not job_id
        or job_id in {".", ".."}
        or Path(job_id).name != job_id
        or "/" in job_id
        or "\\" in job_id
    ):
        raise ValueError("invalid checkpoint request job identity")
    return job_id


def _aware_timestamp(value):
    if type(value) is not str:
        return False
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return False
    return timestamp.tzinfo is not None


def validate_checkpoint_request(value: dict) -> dict:
    """Validate one exact immutable request and return it unchanged."""
    if type(value) is not dict or set(value) != CHECKPOINT_REQUEST_FIELDS:
        raise ValueError("invalid checkpoint request fields")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("invalid checkpoint request version")
    _canonical_request_id(value["request_id"])
    job_ids = value["job_ids"]
    if type(job_ids) is not list:
        raise ValueError("invalid checkpoint request jobs")
    try:
        canonical = [_canonical_job_id(job_id) for job_id in job_ids]
    except ValueError as error:
        raise ValueError("invalid checkpoint request jobs") from error
    if canonical != sorted(set(canonical)):
        raise ValueError("invalid checkpoint request jobs")
    if not _aware_timestamp(value["requested_at"]):
        raise ValueError("invalid checkpoint request timestamp")
    boot_id = value["boot_id"]
    if boot_id is not None and (type(boot_id) is not str or not boot_id):
        raise ValueError("invalid checkpoint request boot identity")
    deadline = value["deadline_monotonic"]
    if (
        type(deadline) not in (int, float)
        or not math.isfinite(deadline)
        or deadline < 0
    ):
        raise ValueError("invalid checkpoint request deadline")
    return value


def observe_boot_id(reader=telegram_api.current_boot_id):
    """Observe the kernel identity that owns a monotonic clock domain."""
    try:
        boot_id = reader()
    except RuntimeError:
        return None
    if boot_id is not None and (type(boot_id) is not str or not boot_id):
        raise ValueError("invalid current boot identity")
    return boot_id


def deadline_boot_matches(request, current_boot_id):
    """Return whether a durable deadline belongs to the observed clock domain."""
    return (
        current_boot_id is not None
        and request["boot_id"] is not None
        and request["boot_id"] == current_boot_id
    )


def checkpoint_deadline_remaining(request, current_boot_id, now):
    """Relate a monotonic deadline only within one known kernel boot."""
    if not deadline_boot_matches(request, current_boot_id):
        return 0.0
    current = now()
    if type(current) not in (int, float) or not math.isfinite(current):
        raise ValueError("invalid checkpoint monotonic observation")
    return max(0.0, request["deadline_monotonic"] - current)


def validate_checkpoint_result(value, request_id, job_id):
    """Validate one request-scoped terminal checkpoint result."""
    request_id = _canonical_request_id(request_id)
    job_id = _canonical_job_id(job_id)
    if type(value) is not dict or set(value) != CHECKPOINT_RESULT_FIELDS:
        raise ValueError("invalid checkpoint result fields")
    session = value.get("opencode_session")
    if (
        type(value.get("schema_version")) is not int
        or value.get("schema_version") != 1
        or value.get("request_id") != request_id
        or value.get("job_id") != job_id
        or type(value.get("state")) is not str
        or value.get("state") not in CHECKPOINT_RESULT_STATES
        or (
            value.get("state") == "checkpointed"
            and (type(session) is not str or not session.startswith("ses_"))
        )
        or (value.get("state") != "checkpointed" and session is not None)
    ):
        raise ValueError("invalid checkpoint result")
    return value


def validate_checkpoint_catalog(value):
    """Decode the relative request/result directories owned by the catalogue."""
    if type(value) is not dict or set(value) != CHECKPOINT_CATALOG_FIELDS:
        raise ValueError("invalid checkpoint catalogue")
    for field in CHECKPOINT_CATALOG_FIELDS:
        directory = value[field]
        if (
            type(directory) is not str
            or not directory
            or Path(directory).name != directory
            or directory in {".", ".."}
            or "/" in directory
            or "\\" in directory
        ):
            raise ValueError("invalid checkpoint catalogue")
    if value["request_directory"] == value["result_directory"]:
        raise ValueError("invalid checkpoint catalogue")
    return value


def checkpoint_paths(store, catalog):
    checkpoint_catalog = validate_checkpoint_catalog(catalog["checkpoint"])
    store = Path(store)
    return (
        store / checkpoint_catalog["request_directory"],
        store / checkpoint_catalog["result_directory"],
    )


def _read_object(path, description):
    if Path(path).is_symlink():
        raise ValueError(f"invalid {description}")
    try:
        return decode_json_object(Path(path).read_bytes(), description)
    except OSError as error:
        raise ValueError(f"invalid {description}") from error


def _job_record(agent_state, job_id):
    job_id = _canonical_job_id(job_id)
    agent_state = Path(agent_state)
    job_directory = agent_state / "jobs"
    if agent_state.is_symlink() or job_directory.is_symlink():
        raise ValueError("invalid checkpoint job directory")
    path = job_directory / f"{job_id}.json"
    value = _read_object(path, "checkpoint job record")
    if (
        type(value) is not dict
        or value.get("id") != job_id
        or value.get("kind") != "agent-task"
        or type(value.get("state")) is not str
    ):
        raise ValueError("invalid checkpoint job record")
    return value


def _session_records(agent_state, job_id, job):
    expected_output = f"logs/runs/{job_id}.opencode.log"
    if job.get("output") != expected_output:
        return []
    ecosystem_root = Path(agent_state).parent
    log_directory = ecosystem_root / "logs"
    run_directory = log_directory / "runs"
    if log_directory.is_symlink() or run_directory.is_symlink():
        return []
    path = ecosystem_root / expected_output
    if path.is_symlink() or not path.is_file():
        return []
    sessions = []
    try:
        with path.open(encoding="utf-8", errors="replace") as source:
            consumed = 0
            for line in source:
                consumed += len(line.encode("utf-8", errors="replace"))
                if consumed > MAXIMUM_SESSION_LOG_BYTES:
                    break
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                session = value.get("sessionID") if type(value) is dict else None
                if type(session) is str and session.startswith("ses_"):
                    sessions.append(session)
    except OSError:
        return []
    return sessions


def verified_handoff_session(agent_state, job_id, claimed_session=None):
    """Resolve a claimed OpenCode session in that job's canonical durable log."""
    try:
        job = _job_record(agent_state, job_id)
    except ValueError:
        return None
    sessions = _session_records(agent_state, job_id, job)
    if claimed_session is None:
        claimed_session = job.get("opencode_session")
        if claimed_session is None and sessions:
            claimed_session = sessions[0]
    if type(claimed_session) is not str or not claimed_session.startswith("ses_"):
        return None
    return claimed_session if claimed_session in sessions else None


def _result(request_id, job_id, state, session=None):
    return {
        "schema_version": 1,
        "request_id": request_id,
        "job_id": job_id,
        "state": state,
        "opencode_session": session,
    }


def _outcome(request, agent_state, job_id, now, current_boot_id):
    if checkpoint_deadline_remaining(request, current_boot_id, now) <= 0:
        return _result(request["request_id"], job_id, "deadline_expired")
    try:
        job = _job_record(agent_state, job_id)
    except ValueError:
        return _result(request["request_id"], job_id, "unsupported")
    if job["state"] in TERMINAL_JOB_STATES:
        return _result(request["request_id"], job_id, "already_terminal")
    if job["state"] not in ACTIVE_JOB_STATES:
        return _result(request["request_id"], job_id, "unsupported")
    session = verified_handoff_session(
        agent_state, job_id, job.get("opencode_session"),
    )
    if session is None:
        return _result(request["request_id"], job_id, "unsupported")
    return _result(request["request_id"], job_id, "checkpointed", session)


def _read_result(path, request_id, job_id):
    return validate_checkpoint_result(
        _read_object(path, "checkpoint result"), request_id, job_id,
    )


def _publish_result(path, value):
    validate_checkpoint_result(value, value["request_id"], value["job_id"])
    try:
        records._create_exclusive_json(path, value)
    except FileExistsError:
        return _read_result(path, value["request_id"], value["job_id"])
    return value


def process_checkpoint_request(
    path: Path,
    agent_state: Path,
    result_root: Path,
    now: Callable,
    *,
    boot_id: Callable = telegram_api.current_boot_id,
) -> int:
    """Publish one immutable terminal result for every exact requested job."""
    path = Path(path)
    if path.parent.is_symlink():
        raise ValueError("invalid checkpoint request directory")
    request = validate_checkpoint_request(_read_object(path, "checkpoint request"))
    current_boot_id = observe_boot_id(boot_id)
    if path.name != f"{request['request_id']}.json":
        raise ValueError("checkpoint request path identity mismatch")
    result_directory = Path(result_root) / request["request_id"]
    if Path(result_root).is_symlink() or result_directory.is_symlink():
        raise ValueError("invalid checkpoint result directory")
    for job_id in request["job_ids"]:
        result_path = result_directory / f"{job_id}.json"
        if result_path.exists() or result_path.is_symlink():
            _read_result(result_path, request["request_id"], job_id)
            continue
        _publish_result(
            result_path,
            _outcome(request, Path(agent_state), job_id, now, current_boot_id),
        )
    return len(request["job_ids"])


def _required_environment(environ, name):
    value = environ.get(name)
    if type(value) is not str or not value:
        raise RuntimeError(f"missing {name}")
    return value


def load_service_config(environ=None):
    if environ is None:
        environ = os.environ
    store = Path(_required_environment(environ, "SURVIVAL_STORE_DIR"))
    catalogue_path = Path(_required_environment(environ, "LIFECYCLE_CATALOG_PATH"))
    try:
        catalogue = decode_json_object(
            catalogue_path.read_bytes(), "lifecycle catalogue",
        )
        request_root, result_root = checkpoint_paths(store, catalogue)
        timing = time_policy.load(Path(_required_environment(environ, "TIME_CONFIG_PATH")))
        poll_seconds = time_policy.seconds(
            timing, "heartbeat", "guardian_poll_seconds",
        )
    except (OSError, ValueError) as error:
        raise RuntimeError(str(error) or "invalid checkpoint service policy") from error
    return {
        "agent_state": Path(_required_environment(environ, "AGENT_STATE_DIR")),
        "request_root": request_root,
        "result_root": result_root,
        "poll_seconds": poll_seconds,
    }


def run_loop(
    config,
    *,
    sleep=time.sleep,
    monotonic=time.monotonic,
    boot_id=telegram_api.current_boot_id,
):
    """Consume configured request records independently of ordinary admission."""
    while True:
        request_root = Path(config["request_root"])
        for path in sorted(request_root.glob("telegram-*.json")):
            try:
                process_checkpoint_request(
                    path,
                    Path(config["agent_state"]),
                    Path(config["result_root"]),
                    monotonic,
                    boot_id=boot_id,
                )
            except (OSError, ValueError):
                continue
        sleep(config["poll_seconds"])


def main():
    run_loop(load_service_config())


if __name__ == "__main__":
    main()
