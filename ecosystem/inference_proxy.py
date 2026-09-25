"""Authenticated, bounded fingertip for ordinary local inference."""
from __future__ import annotations

import concurrent.futures
import fcntl
import hashlib
import http.client
import ipaddress
import json
import math
import os
import secrets
import select
import socket
import threading
import time
import urllib.parse
import uuid
from contextlib import contextmanager
from email.parser import BytesHeaderParser
from pathlib import Path

from ecosystem.inference_capacity import release_parked_sequence, release_sequence
from survival.records import atomic_json


STATE_VERSION = 1
_active_upstreams = {}
_active_upstreams_lock = threading.Lock()
DEFAULT_LIMITS = {
    "header_bytes": 65536,
    "body_bytes": 16777216,
    "stream_chunk_bytes": 65536,
}


def apply_opencode_capacity(config: dict, capacity_record: dict) -> None:
    """Apply observed per-request limits to inference and its compaction model."""
    if (type(capacity_record) is not dict
            or type(capacity_record.get("model_id")) is not str
            or not capacity_record.get("model_id")
            or type(capacity_record.get("opencode_context_tokens")) is not int
            or type(capacity_record.get("opencode_output_tokens")) is not int
            or not 0 < capacity_record["opencode_output_tokens"] < capacity_record["opencode_context_tokens"]):
        raise ValueError("invalid effective inference capacity record")
    models = config.setdefault("provider", {}).setdefault("Lemonade", {}).setdefault("models", {})
    if type(models) is not dict:
        raise ValueError("OpenCode model catalogue must be an object")
    for entry in models.values():
        if type(entry) is dict:
            entry.pop("limit", None)
    context = capacity_record["opencode_context_tokens"]
    output = capacity_record["opencode_output_tokens"]
    models.setdefault(capacity_record["model_id"], {})["limit"] = {
        "context": context, "input": context - output, "output": output,
    }
    selected = "Lemonade/" + capacity_record["model_id"]
    config["model"] = selected
    config["small_model"] = selected
    config.setdefault("compaction", {})["auto"] = True
    config.setdefault("agent", {}).setdefault("compaction", {})["model"] = selected


def opencode_environment(root: Path, capacity_record: dict, credential: bytes) -> dict:
    """Create one anonymous OpenCode configuration; the caller owns the returned fd.

    The selected model's limits are the one validated effective capacity record
    (``opencode_context_tokens`` / ``opencode_output_tokens``). Static capacity
    claims from the base catalogue never reach the memfd: every model's
    ``limit`` is stripped before the selected model's limit is written, so only
    the validated record's values can be present.
    """
    if type(credential) is not bytes or len(credential) != 32:
        raise ValueError("proxy credential must contain exactly 32 bytes")
    if (type(capacity_record) is not dict
            or type(capacity_record.get("model_id")) is not str
            or not capacity_record.get("model_id")
            or type(capacity_record.get("opencode_context_tokens")) is not int
            or capacity_record.get("opencode_context_tokens") <= 0
            or type(capacity_record.get("opencode_output_tokens")) is not int
            or capacity_record.get("opencode_output_tokens") <= 0):
        raise ValueError("invalid effective inference capacity record")
    root = Path(root)
    source = root / "config/executor-opencode.json"
    config = json.loads(source.read_text(encoding="utf-8")) if source.exists() else {
        "provider": {"Lemonade": {"name": "local admitted inference",
                                   "npm": "@ai-sdk/openai-compatible", "models": {}}}}
    provider = config.setdefault("provider", {}).setdefault("Lemonade", {})
    policy_path = root / "config/model-policy.json"
    proxy_base = "http://127.0.0.1:13306/v1"
    if policy_path.exists():
        proxy_base = json.loads(policy_path.read_text(encoding="utf-8")).get(
            "inference_proxy", {}).get("proxy_base", proxy_base)
    validate_loopback_base(proxy_base)
    provider["options"] = {
        "apiKey": credential.hex(),
        "baseURL": proxy_base,
        # Admission and backend scheduling may intentionally leave a request
        # queued for longer than an SDK's ordinary request deadline.
        "timeout": False,
        "headerTimeout": False,
        "chunkTimeout": False,
    }
    apply_opencode_capacity(config, capacity_record)
    descriptor = os.memfd_create("cointos-opencode", os.MFD_CLOEXEC)
    try:
        payload = json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
        written = 0
        while written < len(payload):
            written += os.write(descriptor, payload[written:])
        os.lseek(descriptor, 0, os.SEEK_SET)
        return {
            "environment": {"OPENCODE_CONFIG": f"/proc/self/fd/{descriptor}"},
            "pass_fds": (descriptor,),
            "fd": descriptor,
        }
    except Exception:
        os.close(descriptor)
        raise


def populate_opencode_credential(config: dict, credential: bytes) -> None:
    """Replace the fixed anonymous-memfd placeholder without changing its shape."""
    if type(config) is not dict or type(config.get("fd")) is not int:
        raise ValueError("invalid anonymous OpenCode configuration")
    if type(credential) is not bytes or len(credential) != 32:
        raise ValueError("proxy credential must contain exactly 32 bytes")
    descriptor = config["fd"]
    payload = os.pread(descriptor, os.fstat(descriptor).st_size, 0)
    placeholder = b'"apiKey":"' + (b"0" * 64) + b'"'
    replacement = b'"apiKey":"' + credential.hex().encode("ascii") + b'"'
    if payload.count(placeholder) != 1:
        raise ValueError("OpenCode credential placeholder is absent or ambiguous")
    populated = payload.replace(placeholder, replacement)
    written = 0
    while written < len(populated):
        written += os.pwrite(descriptor, populated[written:], written)
    if os.pread(descriptor, len(populated), 0) != populated:
        raise RuntimeError("OpenCode credential population verification failed")


def validate_loopback_base(value: str) -> dict:
    if type(value) is not str:
        raise ValueError("invalid inference endpoint")
    parsed = urllib.parse.urlsplit(value)
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
        port = parsed.port
    except ValueError as error:
        raise ValueError("invalid inference endpoint") from error
    if (parsed.scheme != "http" or not address.is_loopback or parsed.path != "/v1"
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or port is None):
        raise ValueError("inference endpoint must be an exact loopback http /v1 base")
    return {"host": parsed.hostname, "port": port, "path": parsed.path}


def issue_proxy_credential(root: Path, lease: dict, credential_sink, clock) -> dict:
    """Bind one raw credential to authoritative R1/R3 state and deliver it once."""
    root = Path(root)
    now = _clock(clock)
    secret = secrets.token_bytes(32)
    digest = hashlib.sha256(secret).hexdigest()
    lease_id = lease.get("lease_id") if type(lease) is dict else None
    try:
        with _locked_states(root) as (worker_state, capacity_state, proxy_state, save):
            authoritative = _starting_lease(worker_state, capacity_state, lease_id)
            if _public_binding(authoritative) != _public_binding(lease):
                raise ValueError("inference lease does not match authoritative state")
            worker = worker_state["leases"][authoritative["request"]["worker_lease_id"]]
            _validate_registered_process(worker)
            prior = proxy_state["credentials"].get(lease_id)
            binding = _credential_binding(authoritative, worker)
            if prior is not None:
                if prior["binding"] != binding:
                    raise ValueError("credential lease binding mismatch")
                raise ValueError("credential already issued")
            proxy_state["credentials"][lease_id] = {
                "digest": digest,
                "binding": binding,
                "state": "open",
                "issued_monotonic": now,
                "in_flight": {},
                "completed_requests": 0,
                "claimed_requests": 0,
                "last_backend_termination": None,
            }
            save()
        credential_sink(secret)
    except Exception:
        _discard_credential(root, lease_id, digest)
        raise
    finally:
        secret = b"\0" * len(secret)
    return {"state": "issued", "lease_id": lease_id, "credential_digest": digest}


def authorize_proxy_request(root: Path, metadata: dict, body: dict, clock) -> dict:
    """Atomically authenticate and claim one request before upstream I/O."""
    root = Path(root)
    now = _clock(clock)
    if type(metadata) is not dict or type(body) is not dict:
        return {"status": 400, "error": "invalid request"}
    token = _bearer(metadata.get("authorization"))
    if token is None:
        return {"status": 401, "error": "missing bearer credential"}
    digest = hashlib.sha256(token).hexdigest()
    with _locked_states(root) as (worker_state, capacity_state, proxy_state, save):
        matches = [(lease_id, record) for lease_id, record in proxy_state["credentials"].items()
                   if secrets.compare_digest(record.get("digest", ""), digest)]
        if len(matches) != 1:
            return {"status": 401, "error": "invalid bearer credential"}
        lease_id, credential = matches[0]
        if credential.get("state") in {"parking", "parked", "reacquiring"}:
            return {"status": 425, "error": "inference capacity is being reacquired",
                    "lease_id": lease_id, "credential_state": credential["state"]}
        if credential.get("state") != "open":
            return {"status": 409, "error": "credential is closing or revoked"}
        try:
            lease = _starting_lease(worker_state, capacity_state, lease_id)
            worker = worker_state["leases"][lease["request"]["worker_lease_id"]]
            _validate_registered_process(worker)
            if credential["binding"] != _credential_binding(lease, worker):
                raise ValueError("credential binding changed")
            _validate_request_binding(metadata, body, lease, credential["binding"])
        except ValueError as error:
            return {"status": 403, "error": str(error)}
        request_key = metadata.get("request_id") or body.get("request_id")
        if request_key is not None and (type(request_key) is not str or not request_key):
            return {"status": 400, "error": "invalid request identity"}
        if credential["in_flight"]:
            return {"status": 409, "error": "run already has a request in flight"}
        if request_key and any(item.get("request_id") == request_key
                               for item in credential["in_flight"].values()):
            return {"status": 409, "error": "request is already in flight"}
        proxy_state["generation"] += 1
        claim_id = f"claim-{proxy_state['generation']}-{secrets.token_hex(8)}"
        credential["in_flight"][claim_id] = {
            "request_id": request_key,
            "claimed_monotonic": now,
            "backend": None,
        }
        credential["claimed_requests"] = credential.get(
            "claimed_requests", credential.get("completed_requests", 0)) + 1
        # A new backend round supersedes prior end evidence until this round
        # itself has a verified termination.
        credential["last_backend_termination"] = None
        credential["response_finished"] = False
        save()
        return {"status": 200, "claim_id": claim_id, "lease": _durable(lease),
                "credential_binding": _durable(credential["binding"])}


def handle_proxy_request(root: Path, metadata: dict, body: dict, backend_request, clock) -> dict:
    admission = authorize_proxy_request(root, metadata, body, clock)
    if admission["status"] != 200:
        return admission
    claim_id = admission["claim_id"]
    lease = admission["lease"]
    try:
        result = backend_request({
            "body": _durable(body),
            "lease": lease,
            "backend_sequence": lease["backend_sequence"],
            "claim_id": claim_id,
        })
        if result is None:
            result = {"status": 502, "error": "backend returned no response"}
        if type(result) is not dict:
            raise ValueError("backend response must be a dictionary")
        terminated = type(result.get("termination_observation")) is dict
        _finish_claim(Path(root), lease["lease_id"], claim_id, terminated, result, clock)
        return result
    except Exception:
        _finish_claim(Path(root), lease["lease_id"], claim_id, False, {}, clock)
        raise


def cancel(root: Path, lease_id: str, clock) -> dict:
    """Request cancellation without claiming that an upstream sequence ended."""
    with _active_upstreams_lock:
        upstreams = list(_active_upstreams.get((str(Path(root)), lease_id), ()))
    for upstream in upstreams:
        sock = getattr(upstream, "sock", None)
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        upstream.close()
    now = _clock(clock)
    with _proxy_lock(Path(root)) as (state, save):
        credential = state["credentials"].get(lease_id)
        if credential is None:
            raise ValueError("unknown proxy credential")
        if credential.get("state") == "revoked":
            return {"state": "revoked", "lease_id": lease_id, "in_flight": 0}
        if credential.get("state") == "closing":
            return {"state": "cancellation_requested", "lease_id": lease_id,
                    "in_flight": len(credential["in_flight"])}
        credential["state"] = "closing"
        credential["cancel_requested_monotonic"] = now
        save()
        return {"state": "cancellation_requested", "lease_id": lease_id,
                "in_flight": len(credential["in_flight"])}


def revoke_proxy_credential(root: Path, lease_id: str, observed_end: dict, clock) -> dict:
    """Close a run only after a persisted, verified backend termination."""
    root = Path(root)
    now = _clock(clock)
    with _proxy_lock(root) as (state, save):
        credential = state["credentials"].get(lease_id)
        if credential is None:
            raise ValueError("unknown proxy credential")
        if credential.get("state") == "revoked":
            released = credential.get("released_sequence")
            if (type(released) is not dict or released.get("lease_id") != lease_id
                    or released.get("expected_release_binding")
                    != credential.get("binding", {}).get("release_binding")):
                raise ValueError("revoked credential lacks authoritative sequence result")
            return {"state": "revoked", "lease_id": lease_id,
                    "sequence": _durable(released)}
        if credential["in_flight"]:
            raise ValueError("requests remain in flight")
        termination = _verified_run_end(credential)
        if (type(observed_end) is not dict or observed_end.get("terminated") is not True
                or termination is None or observed_end != termination):
            raise ValueError("backend termination is not verified")
        credential["state"] = "releasing"
        credential["release_requested_monotonic"] = now
        save()
    lease = _capacity_lease(root, lease_id)
    parked_release = credential.get("released_sequence")
    if lease.get("backend_sequence") is None and type(parked_release) is dict:
        released = release_parked_sequence(
            root, lease_id, parked_release, clock)
        with _proxy_lock(root) as (state, save):
            credential = state["credentials"][lease_id]
            credential["state"] = "revoked"
            credential["digest"] = ""
            credential["released_sequence"] = _durable(released)
            credential["revoked_monotonic"] = _clock(clock)
            save()
        return {"state": "revoked", "lease_id": lease_id,
                "sequence": released}
    attestation = {
        "schema_version": 1,
        "binding": _durable(observed_end["binding"]),
        "kind": observed_end.get("kind", "sequence_end"),
        "observer_identity": observed_end["observer_identity"],
        "observer_generation": observed_end["observer_generation"],
        "observed_monotonic": observed_end["observed_monotonic"],
        "clock_domain_id": observed_end["clock_domain_id"],
        "evidence_id": observed_end["evidence_id"],
    }
    released = release_sequence(root, lease_id, attestation, clock)
    if released.get("state") != "released":
        raise RuntimeError("R3 did not accept sequence termination")
    with _proxy_lock(root) as (state, save):
        credential = state["credentials"][lease_id]
        credential["state"] = "revoked"
        credential["digest"] = ""
        credential["released_sequence"] = _durable(released)
        credential["revoked_monotonic"] = _clock(clock)
        save()
    return {"state": "revoked", "lease_id": lease_id, "sequence": released}


def park_proxy_credential(root: Path, lease_id: str, observed_end: dict, clock) -> dict:
    """Release a live session's physical sequence while keeping its bearer valid."""
    root = Path(root)
    now = _clock(clock)
    with _proxy_lock(root) as (state, save):
        credential = state["credentials"].get(lease_id)
        if credential is None:
            raise ValueError("unknown proxy credential")
        if credential.get("state") == "parked":
            released = credential.get("released_sequence")
            if (type(released) is not dict or released.get("lease_id") != lease_id
                    or released.get("expected_release_binding")
                    != credential.get("binding", {}).get("release_binding")):
                raise ValueError("parked credential lacks authoritative sequence result")
            return {"state": "parked", "lease_id": lease_id,
                    "sequence": _durable(released)}
        if credential["in_flight"]:
            raise ValueError("requests remain in flight")
        termination = _verified_run_end(credential)
        if (type(observed_end) is not dict or observed_end.get("terminated") is not True
                or termination is None or observed_end != termination):
            raise ValueError("backend termination is not verified")
        credential["state"] = "parking"
        credential["park_requested_monotonic"] = now
        save()
    lease = _capacity_lease(root, lease_id)
    attestation = {
        "schema_version": 1,
        "binding": _durable(observed_end["binding"]),
        "kind": observed_end.get("kind", "sequence_end"),
        "observer_identity": observed_end["observer_identity"],
        "observer_generation": observed_end["observer_generation"],
        "observed_monotonic": observed_end["observed_monotonic"],
        "clock_domain_id": observed_end["clock_domain_id"],
        "evidence_id": observed_end["evidence_id"],
    }
    try:
        released = release_sequence(root, lease_id, attestation, clock)
        if released.get("state") != "released":
            raise RuntimeError("R3 did not accept sequence termination")
    except Exception:
        # Parking is optional between model steps. If physical release cannot
        # be proved, retain the allocation and keep the logical run usable.
        # Cancellation may have changed parking -> closing meanwhile.
        with _proxy_lock(root) as (state, save):
            credential = state["credentials"].get(lease_id)
            if credential is not None and credential.get("state") == "parking":
                credential["state"] = "open"
                credential.pop("park_requested_monotonic", None)
                save()
        raise
    with _proxy_lock(root) as (state, save):
        credential = state["credentials"][lease_id]
        credential["released_sequence"] = _durable(released)
        credential["parked_monotonic"] = _clock(clock)
        # Cancellation may have changed parking -> closing while R3 released
        # the sequence.  Never reopen that credential after cancellation.
        if credential.get("state") == "parking":
            credential["state"] = "parked"
        elif credential.get("state") != "closing":
            raise RuntimeError("proxy credential changed during physical park")
        final_state = credential["state"]
        save()
    return {"state": final_state, "lease_id": lease_id, "sequence": released}


def reacquire_proxy_credential(root: Path, lease_id: str, inventory: dict, clock) -> dict:
    """Renew a parked logical credential after reacquire_sequence obtains capacity."""
    root = Path(root)
    with _proxy_lock(root) as (state, save):
        credential = state["credentials"].get(lease_id)
        if credential is None:
            raise ValueError("unknown proxy credential")
        if credential.get("state") not in {"parked", "reacquiring"}:
            raise ValueError("proxy credential is not parked or reacquiring")
        if not credential.get("digest"):
            raise ValueError("proxy credential lacks a bearer digest")
        if credential["in_flight"]:
            raise ValueError("requests remain in flight")
        credential["state"] = "reacquiring"
        save()
    from ecosystem import inference_capacity
    sequence = inference_capacity.reacquire_sequence(root, lease_id, inventory, clock)
    if sequence.get("state") not in {"starting", "active"}:
        return {"state": "reacquiring", "lease_id": lease_id, "sequence": sequence}
    with _locked_states(root) as (worker_state, capacity_state, proxy_state, save):
        authoritative = _starting_lease(worker_state, capacity_state, lease_id)
        worker = worker_state["leases"][authoritative["request"]["worker_lease_id"]]
        _validate_registered_process(worker)
        credential = proxy_state["credentials"].get(lease_id)
        if (credential is None or credential.get("state") not in {"reacquiring", "closing"}
                or not credential.get("digest") or credential["in_flight"]):
            raise ValueError("proxy credential is not reacquiring")
        credential["binding"] = _credential_binding(authoritative, worker)
        # Cancellation may arrive while capacity is being reacquired.  Refresh
        # the physical binding either way so cleanup can release the new
        # sequence, but never reopen a closing credential.
        if credential["state"] == "reacquiring":
            credential["state"] = "open"
        final_state = credential["state"]
        credential["reacquired_monotonic"] = _clock(clock)
        credential["claimed_requests"] = 0
        credential["completed_requests"] = 0
        for field in ("released_sequence", "park_requested_monotonic", "parked_monotonic",
                      "last_backend_termination", "last_slot_evidence", "response_finished"):
            credential.pop(field, None)
        save()
    return {"state": final_state, "lease_id": lease_id, "sequence": sequence}


def reconcile_available_capacity(root: Path, clock=time.monotonic) -> dict:
    """Reclaim abandoned capacity before admission, independent of caller cleanup."""
    root = Path(root)
    result = {"released": [], "retained": [], "reconciled_credentials": []}
    # Unissued ghosts must not depend on a proxy credential ever existing.
    from ecosystem import inference_capacity
    capacity_path = root / "state/inference-capacity.json"
    if capacity_path.exists():
        capacity = json.loads(capacity_path.read_text())
        for lease_id, lease in capacity.get("leases", {}).items():
            if lease.get("state") not in {"starting", "active", "preemption_requested", "release_requested"}:
                continue
            try:
                withdrawn = inference_capacity.withdraw_unissued_sequence(root, lease_id, clock)
                if withdrawn.get("state") == "released":
                    result["released"].append(lease_id)
            except (OSError, ValueError, RuntimeError, KeyError, TypeError):
                pass  # Issued leases close through their incarnation-bound proxy evidence below.
    if not (root / "state/inference-proxy.json").exists():
        return result
    # A prior R3 release can outlive a proxy crash between capacity release
    # and bearer revocation. Adopt only that persisted release, under the same
    # locks as both ledgers; this does not assert a new physical termination.
    result["reconciled_credentials"] = reconcile_released_proxy_credentials(root, clock)
    with _proxy_lock(root) as (state, save):
        candidates = [lease_id for lease_id, item in state["credentials"].items()
                      if item.get("state") != "revoked"
                      and _bound_process_ended(item.get("binding", {}).get("process", {})) is True]
    for lease_id in candidates:
        try:
            with _proxy_lock(root) as (state, _save):
                stale = _durable(state["credentials"].get(lease_id, {}))
            for claim_id, claim in stale.get("in_flight", {}).items():
                evidence = claim.get("slot_evidence", {})
                start = evidence.get("start") or {}
                observed = observe_backend_slots(start.get("identity"))
                backend_ended = (
                    type(start.get("identity")) is dict
                    and _bound_process_ended(start["identity"]) is True
                )
                if (not claim.get("request_id") and (
                        backend_ended
                        or (type(observed) is dict
                            and observed.get("identity") == start.get("identity")
                            and observed.get("slots")
                            and all(slot.get("is_processing") is False
                                    for slot in observed["slots"])))):
                    # The bound process died after claiming but before assigning
                    # a backend request identity. An ended exact backend
                    # incarnation or fresh idle slots prove that this ghost
                    # owns no physical execution.
                    _finish_claim(root, lease_id, claim_id, False, {}, clock)
                    continue
                termination = _slot_ended_idle_termination(root, lease_id, claim_id, observed, clock)
                if termination is not None:
                    _finish_claim(root, lease_id, claim_id, True,
                                  {"termination_observation": termination}, clock)
            end = completed_run_termination(root, lease_id, clock)
            if end is None:
                result["retained"].append(lease_id)
                continue
            closed = revoke_proxy_credential(root, lease_id, end, clock)
            if closed.get("sequence", {}).get("state") != "released":
                result["retained"].append(lease_id)
                continue
            result["released"].append(lease_id)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError):
            result["retained"].append(lease_id)
    # Finish abandoned caller/worker bookkeeping after physical reclamation.
    # Live native callers are left untouched; this never replays model work.
    from ecosystem.managed_inference import reconcile_dead_callers
    try:
        result["native"] = reconcile_dead_callers(root, clock)
    except (OSError, ValueError, RuntimeError):
        result["native"] = {"pending": "caller reconciliation unavailable"}
    return result


def reconcile_released_proxy_credentials(root: Path, clock=time.monotonic) -> list[str]:
    """Finish proxy bookkeeping for exact R3 releases already persisted."""
    reconciled = []
    with _locked_states(Path(root)) as (_worker, capacity, proxy, save):
        for lease_id, credential in proxy["credentials"].items():
            lease = capacity.get("leases", {}).get(lease_id)
            if not _can_adopt_released_sequence(lease_id, credential, lease):
                continue
            credential["state"] = "revoked"
            credential["digest"] = ""
            credential["released_sequence"] = _durable(lease)
            credential["revoked_monotonic"] = _clock(clock)
            reconciled.append(lease_id)
            save()
    return reconciled


def _can_adopt_released_sequence(lease_id: str, credential: dict,
                                 lease: dict | None) -> bool:
    """Match an already accepted R3 release to a dead proxy incarnation."""
    if (type(credential) is not dict or type(lease) is not dict
            or credential.get("state") not in {"closing", "releasing"}
            or credential.get("in_flight") != {}
            or lease.get("lease_id") != lease_id
            or lease.get("state") != "released"):
        return False
    binding = credential.get("binding")
    if (type(binding) is not dict or type(binding.get("release_binding")) is not dict
            or type(binding.get("process")) is not dict
            or _bound_process_ended(binding["process"]) is not True):
        return False
    observed = lease.get("observed_release")
    accepted = observed.get("accepted_monotonic") if type(observed) is dict else None
    return (type(observed) is dict
            and observed.get("schema_version") == 1
            and observed.get("kind") in {"sequence_end", "reconciled_absent",
                                         "never_requested", "response_finished"}
            and type(accepted) in (int, float) and math.isfinite(accepted)
            and lease.get("expected_release_binding") == binding["release_binding"]
            and observed.get("binding") == binding["release_binding"]
            and observed.get("observer_identity") == lease.get("release_observer_identity")
            and type(observed.get("evidence_id")) is str
            and bool(observed["evidence_id"]))


def completed_run_termination(root: Path, lease_id: str,
                              clock=time.monotonic, *,
                              require_process_end: bool = True) -> dict | None:
    """Prove physical completion after a request or an entire bound run."""
    root = Path(root)
    with _proxy_lock(Path(root)) as (state, save):
        credential = state["credentials"].get(lease_id)
        if credential is None:
            raise ValueError("unknown proxy credential")
        if credential["in_flight"]:
            return None
        process = credential.get("binding", {}).get("process")
        if type(process) is not dict:
            raise ValueError("proxy credential lacks a bound process")
        if require_process_end and _bound_process_ended(process) is not True:
            return None
        if credential.get("state") == "revoked":
            termination = _verified_run_end(credential)
            return _durable(termination) if termination is not None else None
        credential["state"] = "closing" if require_process_end else "parking"
        identity = credential.get("backend_identity")
        should_probe = (not credential.get("backend_observation_unknown")
                        and type(identity) is dict)
        save()
        termination = _verified_run_end(credential)
        if not should_probe and termination is not None:
            return _durable(termination)
    observation = None
    if should_probe:
        try:
            if _bound_process_ended(identity) is True:
                observation = {
                    "identity": _durable(identity),
                    "backend_instance_ended": True,
                }
            else:
                evidence = credential.get("last_slot_evidence") or {}
                pre, start = evidence.get("pre"), evidence.get("start")
                candidate = observe_backend_slots(_durable(identity)) if pre and start else None
                slot_id = correlate_claim_slot(pre, start, candidate) if candidate else None
                if slot_id is not None and candidate.get("identity") == identity:
                    observation = {"identity": _durable(identity), "slot_id": slot_id,
                                   "slots": [{"id": slot_id, "is_processing": False}]}
                elif credential.get("response_finished") is True:
                    candidate = candidate or observe_backend_slots(_durable(identity))
                    free = [] if candidate is None else [slot for slot in candidate["slots"]
                                                        if slot.get("is_processing") is False]
                    if free and candidate.get("identity") == identity:
                        observation = {"identity": _durable(identity), "response_finished": True,
                                       "slots": _durable(free)}
                if observation is None:
                    candidate = observe_backend_idle(_durable(identity))
                    if _idle_observation_matches(candidate, identity):
                        observation = candidate
        except Exception:
            pass
    with _proxy_lock(root) as (state, save):
        credential = state["credentials"].get(lease_id)
        if (credential is None or credential["in_flight"]
                or (require_process_end and _bound_process_ended(
                    credential["binding"]["process"]) is not True)):
            return None
        termination = _verified_run_end(credential)
        if observation is None and termination is not None:
            return _durable(termination)
        response_finished = credential.get("response_finished") is True
        if (observation is None and not _never_requested(credential)
                and not response_finished):
            # A dead HTTP client does not prove its upstream GPU request ended.
            if not require_process_end and credential.get("state") == "parking":
                credential["state"] = "open"
                save()
            return None
        now = _clock(clock)
        try:
            policy = json.loads((root / "config/resource-policy.json").read_text(
                encoding="utf-8"))["inference_capacity"]
            observer_identity = str(policy["release_observer_identity"])
            clock_domain_id = str(policy["clock_domain_id"])
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
            return None
        generation = int(state["generation"]) + 1
        record_id = uuid.uuid4().hex
        evidence_id = "backend-observations.jsonl#" + record_id
        kind = ("reconciled_absent" if observation is not None else
                "response_finished" if response_finished else "never_requested")
        termination = {
            "terminated": True,
            "kind": kind,
            "binding": _durable(credential["binding"]["release_binding"]),
            "observer_identity": observer_identity,
            "observer_generation": generation,
            "observed_monotonic": now,
            "clock_domain_id": clock_domain_id,
            "evidence_id": evidence_id,
        }
        record = {
            "record_id": record_id,
            "kind": kind,
            "binding": termination["binding"],
            "observed_monotonic": now,
            "evidence_id": evidence_id,
        }
        if observation is None:
            record.update(process=_durable(credential["binding"]["process"]), in_flight=0,
                          response_finished=response_finished)
        elif observation.get("backend_instance_ended") is True:
            record.update(
                identity=_durable(identity),
                backend_instance_ended=True,
                backend_process={
                    "pid": identity.get("pid"),
                    "process_start_ticks": identity.get("process_start_ticks"),
                },
            )
        else:
            record.update(identity=_durable(identity),
                          all_slots_idle=observation.get("all_slots_idle", False),
                          response_finished=observation.get("response_finished", False),
                          slot_id=observation.get("slot_id"), slots=[{"id": slot["id"], "is_processing": False}
                                 for slot in observation["slots"]])
        try:
            _append_backend_observation(Path(root), record)
        except OSError:
            return None
        state["generation"] = generation
        credential["last_backend_termination"] = termination
        save()
        return _durable(termination)


def _verified_run_end(credential):
    termination = credential.get("last_backend_termination")
    if type(termination) is not dict:
        return None
    if termination.get("kind", "sequence_end") in {
            "sequence_end", "reconciled_absent", "response_finished"}:
        return termination
    if termination.get("kind") == "never_requested" and _never_requested(credential):
        return termination
    return None


def _never_requested(credential):
    return type(credential.get("claimed_requests")) is int and credential["claimed_requests"] == 0


def _idle_observation_matches(observation, identity: dict) -> bool:
    if (type(observation) is not dict
            or observation.get("identity") != identity
            or observation.get("all_slots_idle") is not True
            or type(observation.get("slots")) is not list):
        return False
    return all(type(slot) is dict and type(slot.get("id")) is int
               and slot.get("is_processing") is False
               for slot in observation["slots"])


def _bound_process_ended(process: dict) -> bool | None:
    try:
        stat = (Path("/proc") / str(process["pid"]) / "stat").read_text(
            encoding="utf-8")
        observed_ticks = int(stat.rsplit(")", 1)[1].split()[19])
    except FileNotFoundError:
        return True
    except (KeyError, OSError, ValueError, IndexError):
        return None
    return stat.rsplit(")", 1)[1].split()[0] == "Z" or observed_ticks != process.get("process_start_ticks")


def read_proxy_request(connection, limits: dict) -> tuple[dict, dict]:
    limits = {**DEFAULT_LIMITS, **(limits or {})}
    received = bytearray()
    while b"\r\n\r\n" not in received:
        if len(received) >= limits["header_bytes"]:
            raise ValueError("request headers exceed limit")
        chunk = connection.recv(min(4096, limits["header_bytes"] - len(received)))
        if not chunk:
            raise ValueError("incomplete request headers")
        received.extend(chunk)
    header_end = received.index(b"\r\n\r\n") + 4
    if header_end > limits["header_bytes"]:
        raise ValueError("request headers exceed limit")
    header_block = bytes(received[:header_end])
    request_line, raw_headers = header_block.split(b"\r\n", 1)
    try:
        method, target, version = request_line.decode("ascii").split(" ")
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError("invalid HTTP request line") from error
    if (method, target, version) != ("POST", "/v1/chat/completions", "HTTP/1.1"):
        raise ValueError("unsupported proxy request")
    headers = BytesHeaderParser().parsebytes(raw_headers)
    lengths = headers.get_all("Content-Length", [])
    if len(lengths) != 1 or not lengths[0].isdigit():
        raise ValueError("exactly one numeric Content-Length is required")
    if headers.get_all("Transfer-Encoding"):
        raise ValueError("chunked uploads are forbidden")
    length = int(lengths[0])
    if length > limits["body_bytes"]:
        raise ValueError("request body exceeds limit")
    body_bytes = bytearray(received[header_end:])
    while len(body_bytes) < length:
        chunk = connection.recv(min(65536, length - len(body_bytes)))
        if not chunk:
            raise ValueError("incomplete request body")
        body_bytes.extend(chunk)
    if len(body_bytes) != length:
        raise ValueError("request contains trailing bytes")
    try:
        body = json.loads(body_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid JSON request body") from error
    if type(body) is not dict:
        raise ValueError("request body must be an object")
    metadata = {name.lower(): value for name, value in headers.items()}
    return metadata, body


def _json_response_finished(status, payload):
    if status != 200 or not payload:
        return False
    try:
        choices = json.loads(payload).get("choices")
        return (isinstance(choices, list) and bool(choices)
            and all(isinstance(choice, dict) and choice.get("finish_reason")
                    in {"stop", "length", "tool_calls", "function_call"} for choice in choices))
    except (ValueError, AttributeError):
        return False


def _stream_response_finished(status, payload):
    if status != 200 or not payload:
        return False
    return any(line.strip() == b"data: [DONE]" for line in payload.splitlines())


def forward_proxy_response(connection, upstream, lease: dict, observe, clock) -> dict:
    """Forward one response with bounded reads and an explicit termination record."""
    chunk_size = min(int(lease.get("stream_chunk_bytes", 65536)), 65536)
    status = int(getattr(upstream, "status", 200))
    content_type = upstream.getheader("Content-Type", "application/json")
    connection.sendall((f"HTTP/1.1 {status} OK\r\nContent-Type: {content_type}\r\n"
                        "Connection: close\r\n\r\n").encode("ascii"))
    total = 0
    completed_json = bytearray() if "application/json" in content_type else None
    completed_stream = bytearray() if "text/event-stream" in content_type else None
    while True:
        chunk = upstream.read1(chunk_size)
        if not chunk:
            break
        if len(chunk) > chunk_size:
            raise ValueError("upstream exceeded bounded read")
        connection.sendall(chunk)
        total += len(chunk)
        if completed_json is not None:
            if len(completed_json) + len(chunk) <= 8 * 1024 * 1024:
                completed_json.extend(chunk)
            else:
                completed_json = None
        if completed_stream is not None:
            completed_stream.extend(chunk)
            if len(completed_stream) > 65536:
                del completed_stream[:-65536]
    response_finished = (_json_response_finished(status, completed_json)
                         if completed_json is not None
                         else _stream_response_finished(status, completed_stream))
    if observe is None:
        return {"status": status, "bytes_forwarded": total, "terminated": False,
                "response_finished": response_finished}
    evidence = observe({"kind": "backend_terminated", "backend_sequence":
                        lease.get("backend_sequence"), "observed_monotonic": _clock(clock)})
    if type(evidence) is not dict or evidence.get("terminated") is not True:
        raise RuntimeError("backend termination was not verified")
    return {"status": status, "bytes_forwarded": total, **evidence}


def _normalize_survivor_system_messages(body: dict, lease: dict, root: Path) -> dict:
    """Fit OpenCode's system preamble to the emergency model's strict template."""
    request = lease.get("request", {})
    if (request.get("authority_profile") != "sole_survivor"
            or request.get("role") != "sole_survivor"):
        return body
    try:
        resource = json.loads((Path(root) / "state/resource-control.json").read_text(
            encoding="utf-8"))
        emergency = json.loads((Path(root) / "config/resource-policy.json").read_text(
            encoding="utf-8"))["emergency"]
    except (OSError, ValueError, KeyError) as error:
        raise ValueError("emergency template policy is unavailable") from error
    if (resource.get("mode") != "emergency"
            or request.get("owner_identity") !=
            f"executor:{resource.get('sole_survivor_job')}"
            or emergency.get("chat_model") != lease["model_id"]):
        return body
    messages = body.get("messages")
    if type(messages) is not list or any(type(message) is not dict for message in messages):
        raise ValueError("invalid emergency message list")
    systems = [message for message in messages if message.get("role") == "system"]
    if not systems or (len(systems) == 1 and messages[0] is systems[0]):
        return body
    if any(set(message) != {"role", "content"} or type(message["content"]) is not str
           for message in systems):
        raise ValueError("unsupported emergency system message content")
    merged = {"role": "system", "content": "\n\n".join(
        message["content"] for message in systems)}
    return {**body, "messages": [merged] + [
        message for message in messages if message.get("role") != "system"]}


def serve_one_connection(connection, root: Path, config: dict, clock) -> None:
    response_started = False
    try:
        connection.settimeout(float(config.get("read_timeout_seconds", 5)))
        metadata, body = read_proxy_request(connection, config)
        while True:
            admission = authorize_proxy_request(root, metadata, body, clock)
            if admission.get("status") != 425:
                break
            if admission.get("credential_state") == "parking":
                time.sleep(0.05)
                continue
            try:
                from ecosystem import models
                renewed = reacquire_proxy_credential(
                    Path(root), admission["lease_id"], models.snapshot(Path(root)), clock)
            except (OSError, RuntimeError, ValueError):
                # The request remains queued while local facts or capacity are
                # refreshed.  A closing credential is handled on the next
                # authorization pass rather than reopened here.
                time.sleep(0.05)
                continue
            if renewed.get("state") != "open":
                time.sleep(0.05)
        if admission["status"] != 200:
            _send_json(connection, admission["status"], admission)
            return
        lease = admission["lease"]
        try:
            body = _normalize_survivor_system_messages(body, lease, root)
            endpoint = validate_loopback_base(config["backend_base"])
            try:
                snapshot = backend_snapshot(config["backend_base"], lease["model_id"])
            except Exception:
                snapshot = None
            identity = _snapshot_identity(snapshot)
            pre = None
            if identity is not None:
                try:
                    pre = observe_backend_slots(identity)
                except Exception:
                    pre = None
            upstream_connection = http.client.HTTPConnection(
                endpoint["host"], endpoint["port"],
                timeout=float(config.get("backend_connect_timeout_seconds", 10)))
        except Exception:
            _finish_claim(Path(root), lease["lease_id"], admission["claim_id"],
                          False, {}, clock)
            raise
        try:
            _register_upstream(Path(root), lease["lease_id"], upstream_connection)
            _record_backend_identity(Path(root), lease["lease_id"], admission["claim_id"],
                                     lease["backend_sequence"], snapshot, clock)
            upstream_connection.request("POST", "/v1/chat/completions",
                                        body=json.dumps(body, separators=(",", ":")),
                                        headers={"Content-Type": "application/json",
                                                 "Connection": "close"})
            # A connected, admitted request may wait indefinitely for its
            # scheduled turn. Explicit cancellation and lease policy end it.
            upstream_connection.sock.settimeout(None)
            start = None
            if pre is not None:
                try:
                    start = _capture_start_slots(pre)
                except Exception:
                    start = None
            _record_claim_slot_evidence(Path(root), lease["lease_id"],
                                        admission["claim_id"], pre, start, clock)
            upstream = upstream_connection.getresponse()
            response_started = True
            result = forward_proxy_response(connection, upstream,
                                            {**lease, "stream_chunk_bytes": config.get(
                                                "stream_chunk_bytes", 65536)},
                                            None, clock)
            termination = None
            if pre is not None and start is not None:
                try:
                    end = observe_backend_slots(start["identity"])
                except Exception:
                    end = None
                termination = _slot_ended_idle_termination(
                    Path(root), lease["lease_id"], admission["claim_id"], end, clock)
            if termination is not None:
                result = {**result, "termination_observation": termination}
            _finish_claim(Path(root), lease["lease_id"], admission["claim_id"],
                          termination is not None, result, clock)
            if termination is None and result.get("response_finished") is True:
                termination = completed_run_termination(
                    Path(root), lease["lease_id"], clock,
                    require_process_end=False)
            if termination is not None:
                try:
                    park_proxy_credential(
                        Path(root), lease["lease_id"], termination, clock)
                except (OSError, RuntimeError, ValueError):
                    # Failure to prove or persist parking retains the physical
                    # lease; it must not turn a completed response into an
                    # apparent client failure.
                    pass
        except Exception:
            _finish_claim(Path(root), lease["lease_id"], admission["claim_id"], False,
                          {}, clock)
            raise
        finally:
            _unregister_upstream(Path(root), lease["lease_id"], upstream_connection)
            upstream_connection.close()
    except Exception as error:
        if not response_started:
            try:
                _send_json(connection, 400, {"status": 400, "error": str(error)})
            except OSError:
                pass
    finally:
        connection.close()


def serve_proxy(root: Path, config: dict, clock) -> None:
    validate_loopback_base(config["proxy_base"])
    endpoint = validate_loopback_base(config["proxy_base"])
    connections = config.get("connections", 4)
    if type(connections) is not int or connections <= 0:
        raise ValueError("proxy connections must be a positive integer")
    with socket.create_server((endpoint["host"], endpoint["port"]), backlog=connections) as listener, \
            concurrent.futures.ThreadPoolExecutor(max_workers=connections) as pool:
        listener.settimeout(float(config.get("accept_timeout_seconds", 1)))
        while True:
            try:
                connection, _address = listener.accept()
            except socket.timeout:
                continue
            pool.submit(serve_one_connection, connection, Path(root), config, clock)


def _validate_request_binding(metadata: dict, body: dict, lease: dict, binding: dict) -> None:
    request = lease["request"]
    expected = {
        "lease_id": lease["lease_id"],
        "owner_identity": request["owner_identity"],
        "run_id": binding["run_id"],
    }
    for name, value in expected.items():
        supplied = metadata.get(name) or metadata.get(f"x-inference-{name.replace('_', '-')}")
        if supplied is not None and supplied != str(value):
            raise ValueError(f"{name} mismatch")
    if body.get("model") != lease["model_id"]:
        raise ValueError("model does not match lease")
    context = body.get("context_tokens", body.get("ctx_size"))
    if context is not None and context != lease["context_tokens"]:
        raise ValueError("context does not match lease")
    if body.get("max_tokens") != lease["max_output_tokens"]:
        raise ValueError("output does not match lease")
    if type(body.get("stream", False)) is not bool:
        raise ValueError("invalid stream mode")


def _starting_lease(worker_state: dict, capacity_state: dict, lease_id: str | None) -> dict:
    lease = capacity_state.get("leases", {}).get(lease_id)
    if lease is None or lease.get("state") not in {"starting", "active"}:
        raise ValueError("inference lease is not starting or active")
    worker = worker_state.get("leases", {}).get(lease.get("request", {}).get("worker_lease_id"))
    if worker is None or worker.get("state") != "active":
        raise ValueError("worker lease is not active")
    return lease


def _validate_registered_process(worker: dict) -> None:
    process = worker.get("process")
    if type(process) is not dict or type(process.get("pid")) is not int \
            or type(process.get("process_start_ticks")) is not int:
        raise ValueError("worker process is not registered")
    try:
        stat = (Path("/proc") / str(process["pid"]) / "stat").read_text(encoding="utf-8")
        start_ticks = int(stat.rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError) as error:
        raise ValueError("registered worker process is absent") from error
    if start_ticks != process["process_start_ticks"]:
        raise ValueError("registered worker process identity changed")


def _credential_binding(lease: dict, worker: dict) -> dict:
    request = lease["request"]
    worker_request = worker["request"]
    return {
        "lease_id": lease["lease_id"],
        "request_id": request["request_id"],
        "worker_lease_id": request["worker_lease_id"],
        "owner_identity": request["owner_identity"],
        "run_id": worker_request.get("job_id"),
        "run_generation": worker_request.get("agent_generation"),
        "process": _durable(worker["process"]),
        "model_id": lease["model_id"],
        "context_tokens": lease["context_tokens"],
        "max_output_tokens": lease["max_output_tokens"],
        "backend_sequence": lease["backend_sequence"],
        "release_binding": _durable(lease["expected_release_binding"]),
    }


def _public_binding(lease: dict) -> dict:
    if type(lease) is not dict:
        return {}
    return {name: lease.get(name) for name in (
        "lease_id", "state", "model_id", "context_tokens", "max_output_tokens",
        "backend_sequence", "expected_release_binding")}


def _finish_claim(root: Path, lease_id: str, claim_id: str, terminated: bool,
                  result: dict, clock) -> None:
    now = _clock(clock)
    with _proxy_lock(root) as (state, save):
        credential = state["credentials"].get(lease_id)
        if credential is None:
            return
        claim = credential["in_flight"].pop(claim_id, None)
        if claim is None:
            return
        credential["completed_requests"] += 1
        credential["last_slot_evidence"] = _durable(claim.get("slot_evidence"))
        credential["response_finished"] = result.get("response_finished") is True
        if terminated:
            observation = _validated_backend_termination(
                root, credential, claim_id, claim, result, now,
            )
            credential["last_backend_termination"] = observation
        save()


def _validated_backend_termination(root: Path, credential: dict, claim_id: str,
                                   claim: dict, result: dict, now: float) -> dict | None:
    observation = result.get("termination_observation")
    if type(observation) is not dict:
        return None
    try:
        policy = json.loads((root / "config/resource-policy.json").read_text(
            encoding="utf-8"))["inference_capacity"]
        observed_at = float(observation["observed_monotonic"])
        maximum_age = float(policy["release_observation_maximum_age_seconds"])
        valid = (
            observation.get("terminated") is True
            and observation.get("binding") == credential["binding"]["release_binding"]
            and observation.get("claim_id") == claim_id
            and observation.get("request_id") == claim.get("request_id")
            and type(observation.get("request_id")) is str
            and bool(observation["request_id"])
            and observation.get("observer_identity") == policy["release_observer_identity"]
            and type(observation.get("observer_generation")) is int
            and observation["observer_generation"] > 0
            and observation.get("clock_domain_id") == policy["clock_domain_id"]
            and type(observation.get("evidence_id")) is str
            and bool(observation["evidence_id"])
            and observed_at <= now and now - observed_at <= maximum_age
        )
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
        return None
    return _durable(observation) if valid else None


def _slot_ended_idle_termination(root: Path, lease_id: str, claim_id: str,
                                 end, clock) -> dict | None:
    """Prove the claim's single flipped slot is now idle; append evidence."""
    root = Path(root)
    with _proxy_lock(root) as (state, _save):
        credential = state["credentials"].get(lease_id)
        if credential is None or (credential.get("state") != "open"
                and _bound_process_ended(credential.get("binding", {}).get("process", {})) is not True):
            return None
        claim = credential["in_flight"].get(claim_id)
        if claim is None:
            return None
        evidence = claim.get("slot_evidence")
        pre = evidence.get("pre") if type(evidence) is dict else None
        start = evidence.get("start") if type(evidence) is dict else None
        if (type(pre) is not dict or type(start) is not dict
                or pre.get("identity") != start.get("identity")):
            return None
        identity = pre.get("identity")
    if type(end) is not dict or end.get("identity") != identity:
        end = None
    slot_id = correlate_claim_slot(pre, start, end)
    if slot_id is None:
        return None
    with _proxy_lock(root) as (state, save):
        credential = state["credentials"].get(lease_id)
        claim = (None if credential is None
                 else credential["in_flight"].get(claim_id))
        if credential is None or (credential.get("state") != "open"
                and _bound_process_ended(credential.get("binding", {}).get("process", {})) is not True) \
                or claim is None:
            return None
        request_id = claim.get("request_id")
        if type(request_id) is not str or not request_id:
            return None
        try:
            policy = json.loads((root / "config/resource-policy.json").read_text(
                encoding="utf-8"))["inference_capacity"]
            observer_identity = str(policy["release_observer_identity"])
            clock_domain_id = str(policy["clock_domain_id"])
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
            return None
        now = _clock(clock)
        generation = int(state["generation"]) + 1
        record_id = uuid.uuid4().hex
        evidence_id = "backend-observations.jsonl#" + record_id
        termination = {
            "terminated": True,
            "binding": _durable(credential["binding"]["release_binding"]),
            "claim_id": claim_id,
            "request_id": request_id,
            "observer_identity": observer_identity,
            "observer_generation": generation,
            "observed_monotonic": now,
            "clock_domain_id": clock_domain_id,
            "evidence_id": evidence_id,
        }
        record = {
            "record_id": record_id,
            "kind": "slot_ended_idle",
            "binding": termination["binding"],
            "claim_id": claim_id,
            "request_id": request_id,
            "observed_monotonic": now,
            "evidence_id": evidence_id,
            "identity": _durable(identity),
            "slot_id": slot_id,
            "pre": _durable(pre),
            "start": _durable(start),
            "end": _durable(end),
        }
        try:
            _append_backend_observation(root, record)
        except OSError:
            return None
        state["generation"] = generation
        save()
        return _durable(termination)


def _snapshot_identity(snapshot):
    if type(snapshot) is not dict:
        return None
    identity = snapshot.get("identity")
    if type(identity) is not dict:
        return None
    return _durable(identity)


def _record_backend_identity(root: Path, lease_id: str, claim_id: str,
                             backend_sequence: int, snapshot, clock) -> None:
    with _proxy_lock(root) as (state, save):
        credential = state["credentials"].get(lease_id)
        claim = None if credential is None else credential["in_flight"].get(claim_id)
        if claim is None:
            raise ValueError("request claim disappeared before backend start")
        identity = _snapshot_identity(snapshot)
        unknown = identity is None
        if credential.get("backend_identity") is None:
            credential["backend_identity"] = identity
        elif identity is not None and identity != credential["backend_identity"]:
            unknown = True
        if identity is not None \
                and identity.get("model_id") != credential["binding"]["model_id"]:
            unknown = True
        credential["backend_observation_unknown"] = (
            bool(credential.get("backend_observation_unknown")) or unknown)
        claim["backend"] = {
            "observer": "configured-backend",
            "backend_sequence": backend_sequence,
            "started_monotonic": _clock(clock),
            "identity": identity,
        }
        save()


def _sanitized_slot_observation(observation):
    """Keep only the recorded identity and slot id/processing facts."""
    if type(observation) is not dict:
        return None
    identity = observation.get("identity")
    slots = observation.get("slots")
    if type(identity) is not dict or type(slots) is not list:
        return None
    sanitized = []
    for slot in slots:
        if (type(slot) is not dict or type(slot.get("id")) is not int
                or type(slot.get("is_processing")) is not bool):
            return None
        sanitized.append({"id": slot["id"], "is_processing": slot["is_processing"]})
    return {"identity": _durable(identity), "slots": sanitized}


def _record_claim_slot_evidence(root: Path, lease_id: str, claim_id: str,
                                pre, start, clock) -> None:
    """Bind sanitized pre/start slot evidence to the exact in-flight claim."""
    now = _clock(clock)
    with _proxy_lock(root) as (state, save):
        credential = state["credentials"].get(lease_id)
        claim = None if credential is None else credential["in_flight"].get(claim_id)
        if claim is None:
            return
        claim["slot_evidence"] = {
            "pre": _sanitized_slot_observation(pre),
            "start": _sanitized_slot_observation(start),
            "recorded_monotonic": now,
        }
        save()


def _discard_credential(root: Path, lease_id: str | None, digest: str) -> None:
    if lease_id is None:
        return
    with _proxy_lock(root) as (state, save):
        record = state["credentials"].get(lease_id)
        if record is not None and record.get("digest") == digest:
            del state["credentials"][lease_id]
            save()


def _capacity_lease(root: Path, lease_id: str) -> dict:
    value = json.loads((root / "state/inference-capacity.json").read_text(encoding="utf-8"))
    lease = value.get("leases", {}).get(lease_id)
    if lease is None:
        raise ValueError("unknown inference lease")
    return lease


def _bearer(value) -> bytes | None:
    if type(value) is not str or not value.startswith("Bearer "):
        return None
    raw = value[7:]
    try:
        return bytes.fromhex(raw)
    except ValueError:
        return raw.encode("utf-8") if raw else None


def _clock(clock) -> float:
    value = clock()
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("invalid proxy clock")
    return float(value)


def _durable(value):
    return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {"version": STATE_VERSION, "generation": 1, "credentials": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    if (type(value) is not dict or value.get("version") != STATE_VERSION
            or type(value.get("generation")) is not int
            or type(value.get("credentials")) is not dict):
        raise ValueError("invalid inference proxy state")
    return value


@contextmanager
def _proxy_lock(root: Path):
    state_dir = root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    with (state_dir / "inference-proxy.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        path = state_dir / "inference-proxy.json"
        state = _load_state(path)
        dirty = False
        def save():
            nonlocal dirty
            dirty = True
        yield state, save
        if dirty:
            atomic_json(path, state)


def _append_backend_observation(root: Path, record: dict) -> None:
    path = Path(root) / "state" / "backend-observations.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True,
                                separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def _locked_states(root: Path):
    state_dir = root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    paths = [state_dir / name for name in (
        "workload-control.lock", "inference-capacity.lock", "inference-proxy.lock")]
    streams = [path.open("a+b") for path in paths]
    try:
        for stream in streams:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        worker = json.loads((state_dir / "workload-control.json").read_text(encoding="utf-8"))
        capacity = json.loads((state_dir / "inference-capacity.json").read_text(encoding="utf-8"))
        proxy_path = state_dir / "inference-proxy.json"
        proxy = _load_state(proxy_path)
        dirty = False
        def save():
            nonlocal dirty
            dirty = True
        yield worker, capacity, proxy, save
        if dirty:
            atomic_json(proxy_path, proxy)
    finally:
        for stream in reversed(streams):
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            stream.close()


def _send_json(connection, status: int, value: dict) -> None:
    body = json.dumps(value, separators=(",", ":")).encode("utf-8")
    connection.sendall((f"HTTP/1.1 {status} Error\r\nContent-Type: application/json\r\n"
                        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode("ascii") + body)


def _register_upstream(root: Path, lease_id: str, upstream) -> None:
    with _active_upstreams_lock:
        _active_upstreams.setdefault((str(root), lease_id), set()).add(upstream)


def _unregister_upstream(root: Path, lease_id: str, upstream) -> None:
    with _active_upstreams_lock:
        key = (str(root), lease_id)
        values = _active_upstreams.get(key)
        if values is None:
            return
        values.discard(upstream)
        if not values:
            _active_upstreams.pop(key, None)


def _backend_json(base: str, path: str):
    endpoint = validate_loopback_base(base)
    if type(path) is not str or not path.startswith("/"):
        raise ValueError("backend path must be an absolute path")
    connection = http.client.HTTPConnection(endpoint["host"], endpoint["port"], timeout=1)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError(f"backend status {response.status} is not 200")
        payload = response.read(1048577)
        if len(payload) > 1048576:
            raise ValueError("backend response exceeds the bounded read")
    finally:
        connection.close()
    try:
        return json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("backend response is not valid JSON") from error


def _backend_process_identity(pid) -> dict | None:
    if type(pid) is not int or pid <= 0:
        return None
    try:
        stat = (Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8")
        fields = stat.rsplit(")", 1)[1].split()
        state = fields[0]
        start_ticks = int(fields[19])
    except (OSError, ValueError, IndexError):
        return None
    if state in ("Z", "X"):
        return None
    try:
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not boot_id:
        return None
    return {"pid": pid, "process_start_ticks": start_ticks, "boot_id": boot_id}


def backend_snapshot(gateway_base: str, model_id: str) -> dict | None:
    """Capture one verified backend identity, or None when facts are absent."""
    if type(model_id) is not str or not model_id:
        return None
    try:
        health = _backend_json(gateway_base, "/api/v1/health")
    except Exception:
        return None
    entries = health.get("all_models_loaded") if type(health) is dict else None
    if type(entries) is not list:
        return None
    matches = [entry for entry in entries
               if type(entry) is dict and entry.get("model_name") == model_id]
    if len(matches) != 1:
        return None
    entry = matches[0]
    if entry.get("loaded") is not True or entry.get("backend_alive") is not True:
        return None
    if type(entry.get("is_busy")) is not bool:
        return None
    pid = entry.get("pid")
    if type(pid) is not int or pid <= 0:
        return None
    try:
        validate_loopback_base(entry.get("backend_url"))
    except ValueError:
        return None
    backend_base = entry["backend_url"]
    first = _backend_process_identity(pid)
    if first is None:
        return None
    try:
        props = _backend_json(backend_base, "/props")
    except Exception:
        return None
    second = _backend_process_identity(pid)
    if second is None or second != first:
        return None
    total_slots = props.get("total_slots") if type(props) is dict else None
    model_path = props.get("model_path") if type(props) is dict else None
    if type(total_slots) is not int or total_slots <= 0:
        return None
    if type(model_path) is not str or not model_path:
        return None
    return {
        "identity": {
            "gateway_base": gateway_base,
            "backend_base": backend_base,
            "model_id": model_id,
            "pid": pid,
            "process_start_ticks": first["process_start_ticks"],
            "boot_id": first["boot_id"],
            "model_path": model_path,
            "total_slots": total_slots,
        },
        "busy": entry["is_busy"],
    }


def _normalized_slot_states(slots, total_slots):
    """Validate one complete bounded slot list; return id -> is_processing."""
    if type(total_slots) is not int or total_slots <= 0:
        return None
    if type(slots) is not list or len(slots) != total_slots:
        return None
    states = {}
    for slot in slots:
        if type(slot) is not dict:
            return None
        slot_id = slot.get("id")
        if type(slot_id) is not int or not 0 <= slot_id < total_slots \
                or slot_id in states:
            return None
        is_processing = slot.get("is_processing")
        if type(is_processing) is not bool:
            return None
        states[slot_id] = is_processing
    return states


def observe_backend_idle(identity: dict) -> dict | None:
    """Prove every recorded slot is idle without exposing slot contents."""
    if type(identity) is not dict:
        return None
    gateway_base = identity.get("gateway_base")
    model_id = identity.get("model_id")
    if type(gateway_base) is not str or type(model_id) is not str:
        return None
    before = backend_snapshot(gateway_base, model_id)
    if (before is None or before.get("identity") != identity
            or before.get("busy") is not False):
        return None
    try:
        slots = _backend_json(identity["backend_base"], "/slots")
    except Exception:
        return None
    after = backend_snapshot(gateway_base, model_id)
    if (after is None or after.get("identity") != identity
            or after.get("busy") is not False):
        return None
    states = _normalized_slot_states(slots, identity.get("total_slots"))
    if states is None or any(states.values()):
        return None
    return {"identity": dict(identity), "all_slots_idle": True,
            "slots": [{"id": slot_id, "is_processing": False}
                      for slot_id in states]}


def observe_backend_slot_idle(identity: dict, slot_id) -> dict | None:
    """Prove one exact recorded slot is idle without exposing slot contents."""
    if type(identity) is not dict:
        return None
    total_slots = identity.get("total_slots")
    if (type(slot_id) is not int or type(total_slots) is not int
            or not 0 <= slot_id < total_slots):
        return None
    gateway_base = identity.get("gateway_base")
    model_id = identity.get("model_id")
    if type(gateway_base) is not str or type(model_id) is not str:
        return None
    before = backend_snapshot(gateway_base, model_id)
    if before is None or before.get("identity") != identity:
        return None
    try:
        slots = _backend_json(identity["backend_base"], "/slots")
    except Exception:
        return None
    after = backend_snapshot(gateway_base, model_id)
    if after is None or after.get("identity") != identity:
        return None
    states = _normalized_slot_states(slots, total_slots)
    if states is None or states.get(slot_id) is not False:
        return None
    return {"identity": dict(identity), "slot_id": slot_id,
            "slot": {"id": slot_id, "is_processing": False}}


def observe_backend_slots(identity: dict) -> dict | None:
    """Capture one incarnation-bracketed complete sanitized slot state."""
    if type(identity) is not dict:
        return None
    gateway_base = identity.get("gateway_base")
    model_id = identity.get("model_id")
    if type(gateway_base) is not str or type(model_id) is not str:
        return None
    before = backend_snapshot(gateway_base, model_id)
    if before is None or before.get("identity") != identity:
        return None
    try:
        slots = _backend_json(identity["backend_base"], "/slots")
    except Exception:
        return None
    after = backend_snapshot(gateway_base, model_id)
    if after is None or after.get("identity") != identity:
        return None
    states = _normalized_slot_states(slots, identity.get("total_slots"))
    if states is None:
        return None
    return {"identity": dict(identity),
            "slots": [{"id": slot_id, "is_processing": states[slot_id]}
                      for slot_id in states]}


def correlate_claim_slot(pre, start, end):
    """Name the one slot whose false->true start flip is idle at the end."""
    if type(pre) is not dict or type(start) is not dict or type(end) is not dict:
        return None
    identity = pre.get("identity")
    if (type(identity) is not dict or start.get("identity") != identity
            or end.get("identity") != identity):
        return None
    total_slots = identity.get("total_slots")
    pre_states = _normalized_slot_states(pre.get("slots"), total_slots)
    start_states = _normalized_slot_states(start.get("slots"), total_slots)
    end_states = _normalized_slot_states(end.get("slots"), total_slots)
    if pre_states is None or start_states is None or end_states is None:
        return None
    started = [slot_id for slot_id, was_idle in pre_states.items()
               if was_idle is False and start_states[slot_id] is True]
    if len(started) != 1:
        return None
    slot_id = started[0]
    if end_states[slot_id] is not False:
        return None
    return slot_id


def _false_to_true_flips(pre, start):
    """Return slot ids that flipped idle->busy between two complete states."""
    identity = pre.get("identity")
    if type(identity) is not dict or start.get("identity") != identity:
        return None
    total_slots = identity.get("total_slots")
    pre_states = _normalized_slot_states(pre.get("slots"), total_slots)
    start_states = _normalized_slot_states(start.get("slots"), total_slots)
    if pre_states is None or start_states is None:
        return None
    return [slot_id for slot_id, was_idle in pre_states.items()
            if was_idle is False and start_states[slot_id] is True]


def _capture_start_slots(pre, attempts=3):
    """Bounded post-accept bracket: stop at the first observed start flip."""
    identity = pre.get("identity") if type(pre) is dict else None
    if type(identity) is not dict:
        return None
    start = None
    for _attempt in range(attempts):
        try:
            start = observe_backend_slots(identity)
        except Exception:
            return None
        if start is None:
            return None
        if _false_to_true_flips(pre, start):
            return start
    return start


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run the admitted local inference proxy")
    parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    policy = json.loads((root / "config/model-policy.json").read_text(encoding="utf-8"))
    serve_proxy(root, policy["inference_proxy"], time.monotonic)
