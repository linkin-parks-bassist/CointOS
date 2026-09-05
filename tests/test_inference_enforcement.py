import json
import os
import socket
import tempfile
import types
import unittest
from contextlib import contextmanager
from pathlib import Path

from ecosystem.inference_proxy import (
    forward_proxy_response, handle_proxy_request, issue_proxy_credential,
    opencode_environment, read_proxy_request,
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


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(unittest.FunctionTestCase(function) for function in functions)
