import json
import os
import socket
import tempfile
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from ecosystem.inference_proxy import (
    _finish_claim, _record_backend_identity, authorize_proxy_request,
    completed_run_termination, forward_proxy_response, handle_proxy_request,
    issue_proxy_credential, opencode_environment, populate_opencode_credential,
    read_proxy_request, revoke_proxy_credential, serve_one_connection,
)


def process_start_ticks(pid):
    return int((Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()[19])


@contextmanager
def fixture():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "state").mkdir(); (root / "config").mkdir()
        worker_lease_id, lease_id = "worker-1", "inference-1"
        process = {"pid": os.getpid(), "process_start_ticks": process_start_ticks(os.getpid())}
        (root / "state/workload-control.json").write_text(json.dumps({
            "schema_version": 1, "mode": "open", "generation": 1, "owner": None,
            "leases": {worker_lease_id: {"state": "active",
                "request": {"job_id": "run-1", "agent_generation": 2}, "process": process}},
        }))
        lease = {"lease_id": lease_id, "state": "starting",
                 "request": {"request_id": "request-1", "worker_lease_id": worker_lease_id,
                             "owner_identity": "worker:one"},
                 "model_id": "model-a", "context_tokens": 4096,
                 "max_output_tokens": 128, "backend_sequence": 1,
                 "expected_release_binding": {"lease_id": lease_id}}
        (root / "state/inference-capacity.json").write_text(json.dumps({
            "version": 1, "generation": 1, "leases": {lease_id: lease}}))
        (root / "config/resource-policy.json").write_text(json.dumps({
            "inference_capacity": {
                "release_observer_identity": "observer:inference-backend",
                "release_observation_maximum_age_seconds": 5,
                "clock_domain_id": "host-monotonic:boot-one",
            },
        }))
        yield {"root": root, "worker_lease_id": worker_lease_id,
               "lease_id": lease_id, "lease": lease}


def body(**changes):
    return {"model": "model-a", "context_tokens": 4096, "max_tokens": 128,
            "stream": False, **changes}


def issue(value):
    delivered = []
    issue_proxy_credential(value["root"], value["lease"], delivered.append, lambda: 10.0)
    assert len(delivered) == 1
    return delivered[0]


def trusted_result(request, now, evidence_id):
    return {
        "status": 200,
        "termination_observation": {
            "terminated": True,
            "binding": request["lease"]["expected_release_binding"],
            "claim_id": request["claim_id"],
            "request_id": request["body"]["request_id"],
            "observer_identity": "observer:inference-backend",
            "observer_generation": 1,
            "observed_monotonic": now,
            "clock_domain_id": "host-monotonic:boot-one",
            "evidence_id": evidence_id,
        },
    }


def test_unauthenticated_request_never_reaches_backend():
    with fixture() as value:
        backend_calls = []
        result = handle_proxy_request(value["root"], {"authorization": ""}, body(),
                                      backend_calls.append, lambda: 10.0)
        assert result["status"] == 401 and backend_calls == []


def test_forged_body_is_refused_before_backend():
    with fixture() as value:
        secret, backend_calls = issue(value), []
        result = handle_proxy_request(value["root"],
            {"authorization": "Bearer " + secret.hex()}, body(model="forged"),
            backend_calls.append, lambda: 11.0)
        assert result["status"] == 403 and backend_calls == []


def test_sequential_requests_use_one_run_credential():
    with fixture() as value:
        secret = issue(value)
        metadata = {"authorization": "Bearer " + secret.hex()}
        for now in (11.0, 12.0):
            result = handle_proxy_request(value["root"], metadata, body(),
                lambda request: {"status": 200, "body": {}, "terminated": True},
                lambda now=now: now)
            assert result["status"] == 200
        state = json.loads((value["root"] / "state/inference-proxy.json").read_text())
        credential = state["credentials"][value["lease_id"]]
        assert credential["completed_requests"] == 2 and credential["state"] == "open"


def test_backend_crash_does_not_fabricate_sequence_end():
    with fixture() as value:
        secret = issue(value)
        def crash(_request):
            raise ConnectionError("backend disappeared")
        with unittest.TestCase().assertRaises(ConnectionError):
            handle_proxy_request(value["root"],
                {"authorization": "Bearer " + secret.hex()}, body(), crash, lambda: 11.0)
        state = json.loads((value["root"] / "state/inference-proxy.json").read_text())
        credential = state["credentials"][value["lease_id"]]
        assert credential["in_flight"] == {} and credential["last_backend_termination"] is None


def test_later_crash_invalidates_prior_round_termination():
    with fixture() as value:
        secret = issue(value)
        metadata = {"authorization": "Bearer " + secret.hex()}
        handle_proxy_request(
            value["root"], {**metadata, "request_id": "first"},
            body(request_id="first"),
            lambda request: trusted_result(request, 11.0, "ended-first"),
            lambda: 11.0,
        )

        def crash(_request):
            raise ConnectionError("second backend round disappeared")

        with unittest.TestCase().assertRaises(ConnectionError):
            handle_proxy_request(value["root"], metadata, body(), crash, lambda: 12.0)
        proxy_path = value["root"] / "state/inference-proxy.json"
        state = json.loads(proxy_path.read_text())
        credential = state["credentials"][value["lease_id"]]
        credential["binding"]["process"] = {"pid": 2 ** 30,
                                                "process_start_ticks": 1}
        proxy_path.write_text(json.dumps(state))
        assert completed_run_termination(value["root"], value["lease_id"]) is None


def test_missing_backend_response_is_not_termination_evidence():
    with fixture() as value:
        secret = issue(value)
        result = handle_proxy_request(
            value["root"], {"authorization": "Bearer " + secret.hex()}, body(),
            lambda _request: None, lambda: 11.0,
        )
        assert result["status"] == 502
        state = json.loads(
            (value["root"] / "state/inference-proxy.json").read_text())
        assert state["credentials"][value["lease_id"]]["last_backend_termination"] is None


def test_unregistered_process_cannot_receive_credential():
    with fixture() as value:
        state_path = value["root"] / "state/workload-control.json"
        state = json.loads(state_path.read_text())
        state["leases"][value["worker_lease_id"]]["process"] = None
        state_path.write_text(json.dumps(state))
        delivered = []
        with unittest.TestCase().assertRaisesRegex(ValueError, "registered"):
            issue_proxy_credential(value["root"], value["lease"], delivered.append, lambda: 10.0)
        proxy_path = value["root"] / "state/inference-proxy.json"
        assert delivered == []
        assert not (proxy_path.exists() and json.loads(proxy_path.read_text())["credentials"])


def test_opencode_memfd_contains_secret_but_environment_does_not():
    with fixture() as value:
        environment = opencode_environment(value["root"], value["lease"], b"x" * 32)
        try:
            assert (b"x" * 32).hex() not in json.dumps(environment)
            assert environment["pass_fds"] == (environment["fd"],)
            config = json.loads(os.pread(environment["fd"], 65536, 0))
            assert config["provider"]["Lemonade"]["options"]["baseURL"] == \
                "http://127.0.0.1:13306/v1"
        finally:
            os.close(environment["fd"])


def test_placeholder_is_populated_in_the_existing_memfd():
    with fixture() as value:
        environment = opencode_environment(value["root"], value["lease"], b"\0" * 32)
        try:
            descriptor = environment["fd"]
            populate_opencode_credential(environment, b"z" * 32)
            config = json.loads(os.pread(descriptor, 65536, 0))
            assert config["provider"]["Lemonade"]["options"]["apiKey"] == \
                (b"z" * 32).hex()
            assert environment["fd"] == descriptor
        finally:
            os.close(environment["fd"])


def test_completed_run_termination_requires_ended_bound_process():
    with fixture() as value:
        secret = issue(value)
        metadata = {"authorization": "Bearer " + secret.hex()}
        for now in (11.0, 12.0):
            handle_proxy_request(
                value["root"], {**metadata, "request_id": f"request-{now}"},
                body(request_id=f"request-{now}"),
                lambda request, now=now: trusted_result(
                    request, now, f"end-{now}"),
                lambda now=now: now,
            )
        assert completed_run_termination(value["root"], value["lease_id"]) is None
        path = value["root"] / "state/inference-proxy.json"
        state = json.loads(path.read_text())
        state["credentials"][value["lease_id"]]["binding"]["process"] = {
            "pid": 2 ** 30, "process_start_ticks": 1,
        }
        path.write_text(json.dumps(state))
        evidence = completed_run_termination(value["root"], value["lease_id"])
        assert evidence["evidence_id"] == "end-12.0"


def test_unreadable_process_identity_remains_unknown():
    with fixture() as value:
        issue(value)
        with patch("ecosystem.inference_proxy._bound_process_ended", return_value=None):
            assert completed_run_termination(value["root"], value["lease_id"]) is None


def test_revoked_credential_replay_returns_authoritative_sequence():
    with fixture() as value:
        issue(value)
        path = value["root"] / "state/inference-proxy.json"
        state = json.loads(path.read_text())
        credential = state["credentials"][value["lease_id"]]
        released = {**value["lease"], "state": "released"}
        credential.update(state="revoked", digest="", released_sequence=released)
        path.write_text(json.dumps(state))
        replay = revoke_proxy_credential(
            value["root"], value["lease_id"], {}, lambda: 20.0)
        assert replay["state"] == "revoked"
        assert replay["sequence"] == released


def test_fragmented_request_preserves_buffered_body_bytes():
    left, right = socket.socketpair()
    try:
        encoded = json.dumps(body()).encode()
        raw = (b"POST /v1/chat/completions HTTP/1.1\r\nContent-Type: application/json\r\n"
               + f"Content-Length: {len(encoded)}\r\n\r\n".encode() + encoded)
        for index in range(0, len(raw), 7):
            left.sendall(raw[index:index + 7])
        metadata, decoded = read_proxy_request(right, {})
        assert decoded == body() and metadata["content-type"] == "application/json"
    finally:
        left.close(); right.close()


def test_body_limit_refuses_before_decoding():
    left, right = socket.socketpair()
    try:
        left.sendall(b"POST /v1/chat/completions HTTP/1.1\r\nContent-Length: 9\r\n\r\n123456789")
        with unittest.TestCase().assertRaisesRegex(ValueError, "body exceeds"):
            read_proxy_request(right, {"body_bytes": 8})
    finally:
        left.close(); right.close()


def test_sse_chunks_are_forwarded_without_a_false_end():
    chunks, sent, observed = [b"data: one\n\n", b"data: two\n\n", b""], [], []
    upstream = types.SimpleNamespace(
        status=200, getheader=lambda _name, default: "text/event-stream",
        read1=lambda maximum: chunks.pop(0))
    connection = types.SimpleNamespace(sendall=sent.append)
    result = forward_proxy_response(connection, upstream,
        {"backend_sequence": 1},
        lambda record: observed.append(record) or {"terminated": True, "evidence_id": "end-1"},
        lambda: 12.0)
    assert b"data: one\n\n" in sent and result["evidence_id"] == "end-1"
    assert len(observed) == 1


def snapshot(model_id="model-a", pid=4242):
    return {"identity": {"model_id": model_id, "endpoint": "127.0.0.1:13305",
                         "process": {"pid": pid, "start_ticks": 7}},
            "busy": False}


def authorize(value, secret):
    admission = authorize_proxy_request(value["root"],
        {"authorization": "Bearer " + secret.hex()}, body(), lambda: 10.0)
    assert admission["status"] == 200
    return admission


def stored_credential(value):
    state = json.loads((value["root"] / "state/inference-proxy.json").read_text())
    return state["credentials"][value["lease_id"]]


def test_first_backend_identity_is_persisted_on_claim_and_credential():
    with fixture() as value:
        secret = issue(value)
        first = authorize(value, secret)
        _record_backend_identity(value["root"], value["lease_id"],
            first["claim_id"], value["lease"]["backend_sequence"],
            snapshot(), lambda: 11.0)
        credential = stored_credential(value)
        assert credential["backend_identity"] == snapshot()["identity"]
        assert credential["backend_observation_unknown"] is False
        assert credential["in_flight"][first["claim_id"]]["backend"] == {
            "observer": "configured-backend", "backend_sequence": 1,
            "started_monotonic": 11.0, "identity": snapshot()["identity"]}
        _finish_claim(value["root"], value["lease_id"], first["claim_id"],
                      False, {}, lambda: 12.0)
        second = authorize(value, secret)
        _record_backend_identity(value["root"], value["lease_id"],
            second["claim_id"], value["lease"]["backend_sequence"],
            snapshot(), lambda: 13.0)
        credential = stored_credential(value)
        assert credential["backend_identity"] == snapshot()["identity"]
        assert credential["backend_observation_unknown"] is False


def test_missing_snapshot_then_known_identity_stays_unknown():
    with fixture() as value:
        secret = issue(value)
        first = authorize(value, secret)
        _record_backend_identity(value["root"], value["lease_id"],
            first["claim_id"], value["lease"]["backend_sequence"],
            None, lambda: 11.0)
        credential = stored_credential(value)
        assert credential["backend_identity"] is None
        assert credential["backend_observation_unknown"] is True
        assert credential["in_flight"][first["claim_id"]]["backend"]["identity"] is None
        _finish_claim(value["root"], value["lease_id"], first["claim_id"],
                      False, {}, lambda: 12.0)
        second = authorize(value, secret)
        _record_backend_identity(value["root"], value["lease_id"],
            second["claim_id"], value["lease"]["backend_sequence"],
            snapshot(), lambda: 13.0)
        credential = stored_credential(value)
        assert credential["backend_identity"] == snapshot()["identity"]
        assert credential["backend_observation_unknown"] is True


def test_changed_backend_identity_keeps_first_and_stays_unknown():
    with fixture() as value:
        secret = issue(value)
        first = authorize(value, secret)
        _record_backend_identity(value["root"], value["lease_id"],
            first["claim_id"], value["lease"]["backend_sequence"],
            snapshot(), lambda: 11.0)
        _finish_claim(value["root"], value["lease_id"], first["claim_id"],
                      False, {}, lambda: 12.0)
        second = authorize(value, secret)
        _record_backend_identity(value["root"], value["lease_id"],
            second["claim_id"], value["lease"]["backend_sequence"],
            snapshot(pid=999), lambda: 13.0)
        credential = stored_credential(value)
        assert credential["backend_identity"] == snapshot()["identity"]
        assert credential["backend_observation_unknown"] is True
        assert credential["in_flight"][second["claim_id"]]["backend"]["identity"] \
            == snapshot(pid=999)["identity"]


def test_wrong_model_snapshot_becomes_unknown():
    with fixture() as value:
        secret = issue(value)
        first = authorize(value, secret)
        _record_backend_identity(value["root"], value["lease_id"],
            first["claim_id"], value["lease"]["backend_sequence"],
            snapshot(model_id="model-b"), lambda: 11.0)
        credential = stored_credential(value)
        assert credential["backend_identity"] == snapshot(model_id="model-b")["identity"]
        assert credential["backend_observation_unknown"] is True
        assert credential["in_flight"][first["claim_id"]]["backend"]["identity"] \
            == snapshot(model_id="model-b")["identity"]


def test_production_http_eof_does_not_create_sequence_end_evidence():
    with fixture() as value:
        secret = issue(value)
        encoded = json.dumps(body()).encode()
        raw = (b"POST /v1/chat/completions HTTP/1.1\r\n"
               + f"Authorization: Bearer {secret.hex()}\r\n".encode()
               + f"Content-Length: {len(encoded)}\r\n\r\n".encode() + encoded)
        reads = [raw, b""]
        sent = []
        connection = types.SimpleNamespace(
            recv=lambda _maximum: reads.pop(0), sendall=sent.append,
            settimeout=lambda _timeout: None, close=lambda: None,
        )
        upstream = types.SimpleNamespace(
            status=200, getheader=lambda _name, default: "application/json",
            read1=lambda _maximum: b"",
        )
        identities_during_post = []

        def upstream_request(*_args, **_kwargs):
            claim = next(iter(stored_credential(value)["in_flight"].values()))
            identities_during_post.append(claim["backend"]["identity"])

        backend = MagicMock()
        backend.request.side_effect = upstream_request
        backend.getresponse.return_value = upstream
        with patch("ecosystem.inference_proxy.http.client.HTTPConnection",
                   return_value=backend), \
                patch("ecosystem.inference_proxy.backend_snapshot",
                      return_value=snapshot()) as observe:
            serve_one_connection(connection, value["root"], {
                "backend_base": "http://127.0.0.1:13305/v1",
            }, lambda: 11.0)
        observe.assert_called_once_with("http://127.0.0.1:13305/v1", "model-a")
        assert identities_during_post == [snapshot()["identity"]]
        state = json.loads(
            (value["root"] / "state/inference-proxy.json").read_text())
        credential = state["credentials"][value["lease_id"]]
        assert credential["completed_requests"] == 1
        assert credential["last_backend_termination"] is None


def test_only_exact_fresh_trusted_backend_observation_is_retained():
    mutations = (
        lambda observation: observation.update(binding={"lease_id": "wrong"}),
        lambda observation: observation.update(request_id="wrong"),
        lambda observation: observation.update(observed_monotonic=1.0),
        lambda observation: observation.update(clock_domain_id="wrong-clock"),
        lambda observation: observation.update(observer_identity="wrong-observer"),
    )
    for mutate in mutations:
        with fixture() as value:
            secret = issue(value)
            metadata = {"authorization": "Bearer " + secret.hex(),
                        "request_id": "request-exact"}

            def backend(request):
                result = trusted_result(request, 11.0, "candidate-end")
                mutate(result["termination_observation"])
                return result

            handle_proxy_request(
                value["root"], metadata, body(request_id="request-exact"),
                backend, lambda: 11.0,
            )
            state = json.loads(
                (value["root"] / "state/inference-proxy.json").read_text())
            assert state["credentials"][value["lease_id"]][
                "last_backend_termination"] is None


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(unittest.FunctionTestCase(function) for function in functions)
