"""Bounded environmental inspection with durable evidence references (A2).

Discovery runs inspect the environment only through the contracted scope roots
of their executable task contract. read_evidence serves one page under a byte
and item budget; limits are caller-managed remaining budgets, counted across
calls, not per call. record_contribution appends output with job and agent
identity under a job's contracted write paths. Containment is canonical and
symlink-safe; the observation digest covers the whole file, so a source
modified between pages changes the digest and voids the open cursor.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ecosystem import cli
from ecosystem.task_contracts import validate_scope, validate_task_contract


DEFAULT_MAXIMUM_BYTES = 65536
_LIMIT_FIELDS = {"maximum_bytes", "maximum_items"}


def _nonnegative_int(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"invalid evidence {name}")
    return value


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _resolve_within(scope: dict, relative_path: str, kind: str) -> Path:
    """Canonicalize relative_path against the scope workspace and prove it
    stays within the contracted roots for kind, following symlinks."""
    if type(relative_path) is not str or not relative_path:
        raise ValueError("invalid evidence path")
    permitted = scope["read_paths"] if kind == "read" else scope["write_paths"]
    if not permitted:
        raise ValueError(f"no contracted {kind} paths for evidence")
    candidate = (Path(scope["workspace"]) / relative_path).resolve(strict=False)
    for allowed in permitted:
        root = Path(allowed).resolve(strict=False)
        if candidate == root or root in candidate.parents:
            return candidate
    raise ValueError(f"evidence {kind} path escapes contracted scope: {relative_path}")


def _page_boundary(raw: bytes) -> int:
    """Length of the longest UTF-8 prefix of raw ending on a codepoint boundary."""
    if raw and (raw[0] & 0xC0) == 0x80:
        raise ValueError("evidence cursor is not on a UTF-8 boundary")
    cut = len(raw)
    while cut > 0 and (raw[cut - 1] & 0xC0) == 0x80:
        cut -= 1
    if cut == 0:
        return 0
    lead = raw[cut - 1]
    if lead & 0x80 == 0:
        return cut
    width = 2 if lead & 0xE0 == 0xC0 else 3 if lead & 0xF0 == 0xE0 else 4
    return cut - 1 if cut - 1 + width > len(raw) else cut


def _events(text: str, maximum_items: int) -> tuple[str, int]:
    """Whole JSONL events within the item budget; a cut tail line is not
    served, so the next page re-reads it from the same cursor."""
    lines = text.split("\n")
    lines.pop()
    kept: list[str] = []
    items_read = 0
    for line in lines:
        if line:
            try:
                json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError("evidence event is not valid JSON") from error
            if items_read >= maximum_items:
                break
            items_read += 1
        kept.append(line)
    body = "\n".join(kept) + ("\n" if kept else "")
    return body, items_read


def _page(data: bytes, cursor: int, maximum_bytes: int, maximum_items: int,
          relative_path: str) -> tuple[str, int, int, bool]:
    raw = data[cursor:cursor + maximum_bytes]
    raw = raw[:_page_boundary(raw)]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("evidence is not valid UTF-8") from error
    if relative_path.endswith(".jsonl"):
        body, items_read = _events(text, maximum_items)
        next_cursor = cursor + len(body.encode("utf-8"))
        return body, next_cursor, items_read, next_cursor < len(data)
    next_cursor = cursor + len(raw)
    return text, next_cursor, 0, next_cursor < len(data)


def read_evidence(scope: dict, relative_path: str, cursor: int, limits: dict) -> dict:
    """Serve one bounded page of contracted evidence at relative_path.

    Result fields: path (canonical), digest (whole file), observed_at, text,
    next_cursor (byte offset for the next call), truncated, items_read.
    limits holds the remaining maximum_bytes and maximum_items; the caller
    decrements them by the UTF-8 length of text and by items_read, so the
    budget is counted across calls. An exhausted budget serves an empty page
    instead of failing.
    """
    validated = validate_scope(scope)
    if type(cursor) is not int or cursor < 0:
        raise ValueError("invalid evidence cursor")
    if type(limits) is not dict or set(limits) != _LIMIT_FIELDS:
        raise ValueError("invalid evidence limits")
    maximum_bytes = _nonnegative_int(limits["maximum_bytes"], "maximum_bytes")
    maximum_items = _nonnegative_int(limits["maximum_items"], "maximum_items")
    resolved = _resolve_within(validated, relative_path, "read")
    data = resolved.read_bytes()
    if maximum_bytes == 0 or maximum_items == 0:
        # Budget exhausted: serve nothing, but stay honest about whether the
        # file continues, so a caller never mistakes a budget stop for EOF.
        text, next_cursor, items_read, truncated = "", cursor, 0, cursor < len(data)
    else:
        text, next_cursor, items_read, truncated = _page(
            data, cursor, maximum_bytes, maximum_items, relative_path)
    return {
        "path": str(resolved),
        "digest": _digest(data),
        "observed_at": cli.now(),
        "text": text,
        "next_cursor": next_cursor,
        "truncated": truncated,
        "items_read": items_read,
    }


def _durable_job(root: Path, job_id: str, job: dict) -> dict:
    path = root / "state" / "jobs" / f"{job_id}.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"job {job_id} has no durable record") from error
    if type(record) is not dict or record.get("id") != job_id:
        raise ValueError(f"job {job_id} durable record is invalid")
    if type(record.get("task_contract")) is not dict:
        raise ValueError(f"job {job_id} durable record lacks its task contract")
    supplied = job.get("task_contract")
    if type(supplied) is dict and supplied != record["task_contract"]:
        raise ValueError(f"job {job_id} contract drifted from its durable record")
    return record


def record_contribution(root: Path, job: dict, relative_path: str, text: str) -> dict:
    """Append one identified contribution under a job's contracted write path.

    Identity comes from the job's durable record at root/state/jobs; the entry
    is appended, never rewritten, and names the job and agent that produced
    it. The result carries the canonical path, the post-write digest, and the
    observation time.
    """
    job_id = job.get("id") if type(job) is dict else None
    if type(job_id) is not str or not job_id:
        raise ValueError("contribution requires a durable job identity")
    durable = _durable_job(Path(root), job_id, job)
    scope = validate_task_contract(durable["task_contract"])["scope"]
    resolved = _resolve_within(scope, relative_path, "write")
    if type(text) is not str or not text.strip():
        raise ValueError("contribution requires nonempty text")
    stamp = cli.now()
    identity = f"job={job_id} agent={durable.get('agent_name') or 'unassigned'}"
    entry = f"## {stamp} {identity}\n\n{text.rstrip()}\n"
    existing = resolved.read_text(encoding="utf-8") if resolved.is_file() else ""
    cli.atomic_text(resolved, existing + entry)
    cli.audit("evidence.contribution", job_id=job_id, path=relative_path)
    return {"path": str(resolved), "digest": _digest(resolved.read_bytes()),
            "observed_at": stamp}
