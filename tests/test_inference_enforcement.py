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
    _finish_claim, _record_backend_identity, _record_claim_slot_evidence,
    _slot_ended_idle_termination, authorize_proxy_request, cancel,
    completed_run_termination, forward_proxy_response, handle_proxy_request,
    issue_proxy_credential, opencode_environment, populate_opencode_credential,
    read_proxy_request, revoke_proxy_credential, serve_one_connection,
)
from ecosystem.opencode_capacity import effective_inference_capacity, launch_fingerprint


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


def effective_record(model_id="model-a", context=4096, output_reserve=2048, prompt=128):
    command = ["opencode", "serve", "--port", "13308"]
    incarnation = {
        "backend_url": "http://127.0.0.1:13308/v1",
        "pid": 4243,
        "launch_command": command,
        "launch_fingerprint": launch_fingerprint(command),
    }
    layout = {
        "context_mode": "fixed",
        "backend_context_tokens": context,
        "parallel_sequences": 1,
        "context_tokens_per_sequence": context,
        "preallocated_context_tokens": context,
    }
    observation = {
        "selected_model_id": model_id,
        "observed_model_id": model_id,
        "backend_incarnation": incarnation,
        "observed_at": 1000.0,
        "evidence": "observation:backend:one",
        "prompt_estimate_tokens": prompt,
        "backend_output_ceiling": None,
        "layout": layout,
    }
    client = {"version": "1.18.30", "qualified": True, "maximum_output_tokens": 32000}
    policy = {"output_reserve_tokens": output_reserve, "rollover_fraction": 0.75,
              "max_age_seconds": 300}
    return effective_inference_capacity(observation, client, policy, 1050.0)


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


def test_later_crash_uses_dead_owner_evidence_after_prior_end_is_invalidated():
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
        evidence = completed_run_termination(value["root"], value["lease_id"])
        assert evidence["kind"] == "owner_process_ended"


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
        environment = opencode_environment(value["root"], effective_record(), b"x" * 32)
        try:
            assert (b"x" * 32).hex() not in json.dumps(environment)
            assert environment["pass_fds"] == (environment["fd"],)
            config = json.loads(os.pread(environment["fd"], 65536, 0))
            options = config["provider"]["Lemonade"]["options"]
            assert options["baseURL"] == "http://127.0.0.1:13306/v1"
            assert options["timeout"] is False
            assert options["headerTimeout"] is False
            assert options["chunkTimeout"] is False
        finally:
            os.close(environment["fd"])


def test_placeholder_is_populated_in_the_existing_memfd():
    with fixture() as value:
        environment = opencode_environment(value["root"], effective_record(), b"\0" * 32)
        try:
            descriptor = environment["fd"]
            populate_opencode_credential(environment, b"z" * 32)
            config = json.loads(os.pread(descriptor, 65536, 0))
            assert config["provider"]["Lemonade"]["options"]["apiKey"] == \
                (b"z" * 32).hex()
            assert environment["fd"] == descriptor
        finally:
            os.close(environment["fd"])


def _excessive_base(root):
    base = {
        "provider": {"Lemonade": {
            "name": "Lemonade Server (local)",
            "npm": "@ai-sdk/openai-compatible",
            "models": {
                "model-a": {"name": "A",
                            "limit": {"context": 999999, "output": 999999}},
                "model-b": {"name": "B",
                            "limit": {"context": 888888, "output": 888888}},
            },
        }},
        "permission": {"*": "allow", "webfetch": "deny", "websearch": "deny"},
    }
    (root / "config/executor-opencode.json").write_text(json.dumps(base),
                                                        encoding="utf-8")


def test_opencode_memfd_encodes_only_the_effective_record():
    with fixture() as value:
        _excessive_base(value["root"])
        record = effective_record("model-a", context=4096, output_reserve=2048)
        environment = opencode_environment(value["root"], record, b"x" * 32)
        try:
            config = json.loads(os.pread(environment["fd"], 65536, 0))
            models = config["provider"]["Lemonade"]["models"]
            assert models["model-a"]["limit"] == {"context": 4096, "output": 2048}
            serialized = json.dumps(config)
            assert "999999" not in serialized
            assert "888888" not in serialized
            options = config["provider"]["Lemonade"]["options"]
            assert options["baseURL"] == "http://127.0.0.1:13306/v1"
            assert config["permission"] == {"*": "allow", "webfetch": "deny",
                                            "websearch": "deny"}
        finally:
            os.close(environment["fd"])


def test_opencode_encoder_consumes_validated_record_limits():
    with fixture() as value:
        record = effective_record("model-a", context=4096, output_reserve=2048)
        environment = opencode_environment(value["root"], record, b"x" * 32)
        try:
            config = json.loads(os.pread(environment["fd"], 65536, 0))
            assert config["provider"]["Lemonade"]["models"]["model-a"]["limit"] == \
                {"context": record["opencode_context_tokens"],
                 "output": record["opencode_output_tokens"]}
        finally:
            os.close(environment["fd"])


def _raises_value_error(fn):
    try:
        fn()
    except ValueError:
        return True
    return False


def test_opencode_encoder_rejects_independent_lease_values():
    with fixture() as value:
        lease = {"model_id": "model-a", "context_tokens": 4096,
                 "max_output_tokens": 128}
        assert _raises_value_error(
            lambda: opencode_environment(value["root"], lease, b"x" * 32))


def test_opencode_encoder_rejects_invalid_record():
    with fixture() as value:
        good = effective_record("model-a", context=4096, output_reserve=2048)
        for key, bad in (("model_id", None),
                         ("opencode_context_tokens", "4096"),
                         ("opencode_output_tokens", -1)):
            record = dict(good)
            record[key] = bad
            assert _raises_value_error(
                lambda record=record: opencode_environment(value["root"], record,
                                                           b"x" * 32))


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


def dead_process(value, **credential_changes):
    path = value["root"] / "state/inference-proxy.json"
    state = json.loads(path.read_text())
    credential = state["credentials"][value["lease_id"]]
    credential["binding"]["process"] = {"pid": 2 ** 30, "process_start_ticks": 1}
    credential.update(credential_changes)
    path.write_text(json.dumps(state))


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


def test_close_never_probes_live_unknown_or_claimed_worker():
    with fixture() as value:
        issue(value)
        with patch("ecosystem.inference_proxy.observe_backend_idle") as probe:
            assert completed_run_termination(value["root"], value["lease_id"]) is None
            probe.assert_not_called()
    with fixture() as value:
        issue(value)
        with patch("ecosystem.inference_proxy._bound_process_ended",
                   return_value=None), \
             patch("ecosystem.inference_proxy.observe_backend_idle") as probe:
            assert completed_run_termination(value["root"], value["lease_id"]) is None
            probe.assert_not_called()
    with fixture() as value:
        issue(value)
        dead_process(value, in_flight={"claim-x": {"request_id": "request-1"}})
        with patch("ecosystem.inference_proxy.observe_backend_idle") as probe:
            assert completed_run_termination(value["root"], value["lease_id"]) is None
            probe.assert_not_called()


def test_close_without_recorded_identity_returns_only_stored_evidence():
    with fixture() as value:
        secret = issue(value)
        metadata = {"authorization": "Bearer " + secret.hex()}
        handle_proxy_request(
            value["root"], {**metadata, "request_id": "request-1"},
            body(request_id="request-1"),
            lambda request: trusted_result(request, 12.0, "end-12.0"),
            lambda: 12.0)
        dead_process(value)
        with patch("ecosystem.inference_proxy.observe_backend_idle") as probe:
            evidence = completed_run_termination(value["root"], value["lease_id"])
            probe.assert_not_called()
        assert evidence["evidence_id"] == "end-12.0"
        assert stored_credential(value)["state"] == "closing"


def test_close_without_identity_uses_dead_owner_evidence():
    with fixture() as value:
        issue(value)
        dead_process(value)
        with patch("ecosystem.inference_proxy.observe_backend_idle") as probe:
            evidence = completed_run_termination(value["root"], value["lease_id"])
            probe.assert_not_called()
        assert evidence["kind"] == "owner_process_ended"
        assert stored_credential(value)["last_backend_termination"] == evidence


def test_sticky_backend_unknown_close_uses_dead_owner_evidence_without_probe():
    with fixture() as value:
        issue(value)
        dead_process(value, backend_identity=snapshot()["identity"],
                     backend_observation_unknown=True)
        with patch("ecosystem.inference_proxy.observe_backend_idle") as probe:
            evidence = completed_run_termination(value["root"], value["lease_id"])
            probe.assert_not_called()
        assert evidence["kind"] == "owner_process_ended"


def test_unreliable_idle_probe_falls_back_to_dead_owner_evidence():
    for kwargs in (
        {"return_value": None},
        {"return_value": {"identity": snapshot()["identity"],
                          "all_slots_idle": False,
                          "slots": [{"id": 0, "is_processing": True}]}},
        {"return_value": {"identity": {"model_id": "other"},
                          "all_slots_idle": True, "slots": []}},
        {"return_value": {"identity": snapshot()["identity"],
                          "all_slots_idle": True, "slots": [{"id": 0}]}},
        {"side_effect": OSError("backend unreachable")},
    ):
        with fixture() as value:
            issue(value)
            dead_process(value, backend_identity=snapshot()["identity"])
            with patch("ecosystem.inference_proxy.observe_backend_idle", **kwargs):
                evidence = completed_run_termination(value["root"], value["lease_id"])
            assert evidence["kind"] == "owner_process_ended"
            assert stored_credential(value)["last_backend_termination"] == evidence


def test_changed_credential_during_probe_yields_no_proof():
    with fixture() as value:
        issue(value)
        dead_process(value, backend_identity=snapshot()["identity"])

        def probe_and_mutate(_identity):
            path = value["root"] / "state/inference-proxy.json"
            state = json.loads(path.read_text())
            state["credentials"][value["lease_id"]]["in_flight"]["claim-x"] = {
                "request_id": "request-1"}
            path.write_text(json.dumps(state))
            return {"identity": snapshot()["identity"], "all_slots_idle": True,
                    "slots": [{"id": 0, "is_processing": False}]}

        with patch("ecosystem.inference_proxy.observe_backend_idle",
                   side_effect=probe_and_mutate):
            assert completed_run_termination(value["root"], value["lease_id"]) is None
        assert stored_credential(value)["last_backend_termination"] is None
        assert not (value["root"] / "state/backend-observations.jsonl").exists()


def test_fresh_idle_probe_persists_reconciled_absent_proof():
    with fixture() as value:
        issue(value)
        dead_process(value, backend_identity=snapshot()["identity"])
        idle = {"identity": snapshot()["identity"], "all_slots_idle": True,
                "slots": [{"id": 3, "is_processing": False},
                          {"id": 4, "is_processing": False}]}
        with patch("ecosystem.inference_proxy.observe_backend_idle",
                   return_value=idle) as probe:
            evidence = completed_run_termination(
                value["root"], value["lease_id"], lambda: 55.0)
        probe.assert_called_once_with(snapshot()["identity"])
        assert evidence is not None
        assert evidence["terminated"] is True
        assert evidence["kind"] == "reconciled_absent"
        assert evidence["binding"] == value["lease"]["expected_release_binding"]
        assert evidence["observer_identity"] == "observer:inference-backend"
        assert type(evidence["observer_generation"]) is int
        assert evidence["observer_generation"] > 0
        assert evidence["observed_monotonic"] == 55.0
        assert evidence["clock_domain_id"] == "host-monotonic:boot-one"
        assert type(evidence["evidence_id"]) is str and evidence["evidence_id"]
        state = json.loads((value["root"] / "state/inference-proxy.json").read_text())
        assert state["generation"] == evidence["observer_generation"]
        credential = stored_credential(value)
        assert credential["state"] == "closing"
        assert credential["last_backend_termination"] == evidence
        lines = (value["root"] / "state/backend-observations.jsonl").read_text() \
            .splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["record_id"]
        assert record["kind"] == "reconciled_absent"
        assert record["binding"] == evidence["binding"]
        assert record["observed_monotonic"] == 55.0
        assert record["evidence_id"] == evidence["evidence_id"]
        assert record["identity"] == snapshot()["identity"]
        assert record["all_slots_idle"] is True
        assert record["slots"] == idle["slots"]
        assert "backend-observations.jsonl" in evidence["evidence_id"]
        assert record["record_id"] in evidence["evidence_id"]


def test_recorded_identity_refreshes_old_response_observation():
    with fixture() as value:
        secret = issue(value)
        metadata = {"authorization": "Bearer " + secret.hex()}
        handle_proxy_request(
            value["root"], {**metadata, "request_id": "request-1"},
            body(request_id="request-1"),
            lambda request: trusted_result(request, 12.0, "end-12.0"),
            lambda: 12.0)
        dead_process(value, backend_identity=snapshot()["identity"])
        idle = {"identity": snapshot()["identity"], "all_slots_idle": True,
                "slots": [{"id": 0, "is_processing": False}]}
        with patch("ecosystem.inference_proxy.observe_backend_idle",
                   return_value=idle):
            evidence = completed_run_termination(
                value["root"], value["lease_id"], lambda: 55.0)
        assert evidence["kind"] == "reconciled_absent"
        assert evidence["evidence_id"] != "end-12.0"
        assert evidence["observed_monotonic"] == 55.0
        assert stored_credential(value)["last_backend_termination"] == evidence


def test_failed_evidence_append_yields_no_proof():
    with fixture() as value:
        issue(value)
        dead_process(value, backend_identity=snapshot()["identity"])
        idle = {"identity": snapshot()["identity"], "all_slots_idle": True,
                "slots": [{"id": 0, "is_processing": False}]}
        with patch("ecosystem.inference_proxy.observe_backend_idle",
                   return_value=idle), \
             patch("ecosystem.inference_proxy._append_backend_observation",
                   side_effect=OSError("disk full")) as append:
            assert completed_run_termination(
                value["root"], value["lease_id"], lambda: 55.0) is None
            append.assert_called_once()
        credential = stored_credential(value)
        assert credential["last_backend_termination"] is None
        assert not (value["root"] / "state/backend-observations.jsonl").exists()


def test_revoke_preserves_reconciled_absent_attestation():
    with fixture() as value:
        issue(value)
        dead_process(value, backend_identity=snapshot()["identity"])
        idle = {"identity": snapshot()["identity"], "all_slots_idle": True,
                "slots": [{"id": 0, "is_processing": False}]}
        with patch("ecosystem.inference_proxy.observe_backend_idle",
                   return_value=idle):
            evidence = completed_run_termination(
                value["root"], value["lease_id"], lambda: 55.0)
        attested = []
        released = {"state": "released", "lease_id": value["lease_id"]}
        with patch("ecosystem.inference_proxy.release_sequence",
                   side_effect=lambda root, lease, attestation, clock:
                   attested.append(attestation) or released):
            result = revoke_proxy_credential(value["root"], value["lease_id"],
                                             evidence, lambda: 55.0)
        assert result["state"] == "revoked"
        assert result["sequence"] == released
        assert attested[0]["kind"] == "reconciled_absent"
        assert attested[0]["binding"] == evidence["binding"]
        assert attested[0]["evidence_id"] == evidence["evidence_id"]
        assert attested[0]["observed_monotonic"] == 55.0
        assert stored_credential(value)["state"] == "revoked"


def test_revoke_defaults_sequence_end_for_trusted_adapter_evidence():
    with fixture() as value:
        secret = issue(value)
        metadata = {"authorization": "Bearer " + secret.hex()}
        handle_proxy_request(
            value["root"], {**metadata, "request_id": "request-1"},
            body(request_id="request-1"),
            lambda request: trusted_result(request, 12.0, "end-12.0"),
            lambda: 12.0)
        dead_process(value)
        evidence = completed_run_termination(value["root"], value["lease_id"],
                                             lambda: 55.0)
        assert evidence["evidence_id"] == "end-12.0"
        attested = []
        released = {"state": "released", "lease_id": value["lease_id"]}
        with patch("ecosystem.inference_proxy.release_sequence",
                   side_effect=lambda root, lease, attestation, clock:
                   attested.append(attestation) or released):
            result = revoke_proxy_credential(value["root"], value["lease_id"],
                                             evidence, lambda: 55.0)
        assert result["state"] == "revoked"
        assert attested[0]["kind"] == "sequence_end"


def test_production_eof_close_proves_absence_only_from_fresh_probe():
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
        backend = MagicMock()
        backend.getresponse.return_value = upstream
        with patch("ecosystem.inference_proxy.http.client.HTTPConnection",
                   return_value=backend) as connection_factory, \
             patch("ecosystem.inference_proxy.backend_snapshot",
                   return_value=snapshot()):
            serve_one_connection(connection, value["root"], {
                "backend_base": "http://127.0.0.1:13305/v1",
            }, lambda: 11.0)
        connection_factory.assert_called_once_with("127.0.0.1", 13305, timeout=10.0)
        backend.sock.settimeout.assert_called_once_with(None)
        assert stored_credential(value)["last_backend_termination"] is None
        assert stored_credential(value)["backend_identity"] == snapshot()["identity"]
        dead_process(value)
        idle = {"identity": snapshot()["identity"], "all_slots_idle": True,
                "slots": [{"id": 0, "is_processing": False}]}
        with patch("ecosystem.inference_proxy.observe_backend_idle",
                   return_value=idle) as probe:
            evidence = completed_run_termination(
                value["root"], value["lease_id"], lambda: 55.0)
        probe.assert_called_once_with(snapshot()["identity"])
        assert evidence["kind"] == "reconciled_absent"
        assert evidence["observed_monotonic"] == 55.0
        attested = []
        released = {"state": "released", "lease_id": value["lease_id"]}
        with patch("ecosystem.inference_proxy.release_sequence",
                   side_effect=lambda root, lease, attestation, clock:
                   attested.append(attestation) or released):
            result = revoke_proxy_credential(value["root"], value["lease_id"],
                                             evidence, lambda: 55.0)
        assert result["state"] == "revoked"
        assert attested[0]["kind"] == "reconciled_absent"
        assert stored_credential(value)["state"] == "revoked"


SLOT_IDENTITY = {**snapshot()["identity"], "total_slots": 2}


def slot_states(states, private=None):
    slots = []
    for slot_id, state in states:
        slot = {"id": slot_id, "is_processing": state}
        if private is not None:
            slot.update(private)
        slots.append(slot)
    return {"identity": SLOT_IDENTITY, "slots": slots}


def add_second_lease(value):
    root = value["root"]
    worker = json.loads((root / "state/workload-control.json").read_text())
    capacity = json.loads((root / "state/inference-capacity.json").read_text())
    worker_lease_id, lease_id = "worker-2", "inference-2"
    worker["leases"][worker_lease_id] = {
        "state": "active",
        "request": {"job_id": "run-2", "agent_generation": 3},
        "process": {"pid": os.getpid(),
                    "process_start_ticks": process_start_ticks(os.getpid())}}
    lease = {"lease_id": lease_id, "state": "starting",
             "request": {"request_id": "request-2",
                         "worker_lease_id": worker_lease_id,
                         "owner_identity": "worker:two"},
             "model_id": "model-a", "context_tokens": 4096,
             "max_output_tokens": 128, "backend_sequence": 2,
             "expected_release_binding": {"lease_id": lease_id}}
    capacity["leases"][lease_id] = lease
    (root / "state/workload-control.json").write_text(json.dumps(worker))
    (root / "state/inference-capacity.json").write_text(json.dumps(capacity))
    return lease


def issue_for(value, lease):
    delivered = []
    issue_proxy_credential(value["root"], lease, delivered.append, lambda: 10.0)
    assert len(delivered) == 1
    return delivered[0]


def admit_with_slot_evidence(value, pre, start):
    secret = issue(value)
    admission = authorize_proxy_request(
        value["root"], {"authorization": "Bearer " + secret.hex(),
                        "request_id": "request-1"},
        body(request_id="request-1"), lambda: 11.0)
    assert admission["status"] == 200
    claim_id = admission["claim_id"]
    _record_claim_slot_evidence(value["root"], value["lease_id"], claim_id,
                                pre, start, lambda: 12.0)
    return claim_id, secret


def e2e_plumbing(value, secret, events):
    def upstream_request(*_args, **_kwargs):
        events.append("request")

    def upstream_getresponse():
        events.append("getresponse")
        return types.SimpleNamespace(
            status=200,
            getheader=lambda _name, _default: "application/json",
            read1=lambda _maximum: (events.append("read1"), b"")[1])
    backend = MagicMock()
    backend.request.side_effect = upstream_request
    backend.getresponse.side_effect = upstream_getresponse
    encoded = json.dumps(body(request_id="request-1")).encode()
    raw = (b"POST /v1/chat/completions HTTP/1.1\r\n"
           + f"Authorization: Bearer {secret.hex()}\r\n".encode()
           + f"Content-Length: {len(encoded)}\r\n\r\n".encode() + encoded)
    reads = [raw, b""]
    connection = types.SimpleNamespace(
        recv=lambda _maximum: reads.pop(0), sendall=lambda _chunk: None,
        settimeout=lambda _timeout: None, close=lambda: None)
    return backend, connection


def test_slot_evidence_stored_on_claim_is_sanitized():
    with fixture() as value:
        claim_id, _secret = admit_with_slot_evidence(
            value,
            slot_states([(0, False), (1, False)], private={"prompt": "p0"}),
            slot_states([(0, True), (1, False)], private={"session": "s0"}))
        evidence = stored_credential(value)["in_flight"][claim_id]["slot_evidence"]
        assert evidence["pre"] == slot_states([(0, False), (1, False)])
        assert evidence["start"] == slot_states([(0, True), (1, False)])
        assert type(evidence["recorded_monotonic"]) is float
        assert "prompt" not in json.dumps(evidence)
        assert "session" not in json.dumps(evidence)
    with fixture() as value:
        issue(value)
        _record_claim_slot_evidence(
            value["root"], value["lease_id"], "claim-unknown",
            slot_states([(0, False)]), slot_states([(0, True)]), lambda: 12.0)
        assert "slot_evidence" not in (
            value["root"] / "state/inference-proxy.json").read_text()


def test_concurrent_claims_unique_flip_releases_one_while_peer_busy():
    with fixture() as value:
        second = add_second_lease(value)
        secret_a = issue(value)
        secret_b = issue_for(value, second)
        admission_a = authorize_proxy_request(
            value["root"], {"authorization": "Bearer " + secret_a.hex(),
                            "request_id": "request-1"},
            body(request_id="request-1"), lambda: 11.0)
        admission_b = authorize_proxy_request(
            value["root"], {"authorization": "Bearer " + secret_b.hex(),
                            "request_id": "request-2"},
            body(request_id="request-2"), lambda: 11.0)
        assert admission_a["status"] == 200 and admission_b["status"] == 200
        claim_a, claim_b = admission_a["claim_id"], admission_b["claim_id"]
        _record_claim_slot_evidence(
            value["root"], value["lease_id"], claim_a,
            slot_states([(0, False), (1, False)]),
            slot_states([(0, True), (1, False)], private={"prompt": "p0"}),
            lambda: 12.0)
        _record_claim_slot_evidence(
            value["root"], second["lease_id"], claim_b,
            slot_states([(0, True), (1, False)]),
            slot_states([(0, True), (1, True)]), lambda: 12.0)
        credential = stored_credential(value)
        assert credential["in_flight"][claim_a]["slot_evidence"]["start"] == \
            slot_states([(0, True), (1, False)])
        termination = _slot_ended_idle_termination(
            value["root"], value["lease_id"], claim_a,
            slot_states([(0, False), (1, True)]), lambda: 13.0)
        assert termination is not None
        assert termination["terminated"] is True
        assert termination["claim_id"] == claim_a
        assert termination["request_id"] == "request-1"
        assert termination["binding"] == value["lease"]["expected_release_binding"]
        assert termination["observer_identity"] == "observer:inference-backend"
        assert type(termination["observer_generation"]) is int
        assert termination["observer_generation"] > 0
        assert termination["observed_monotonic"] == 13.0
        assert termination["clock_domain_id"] == "host-monotonic:boot-one"
        assert type(termination["evidence_id"]) is str
        assert termination["evidence_id"]
        _finish_claim(value["root"], value["lease_id"], claim_a, True,
                      {"termination_observation": termination}, lambda: 13.0)
        stored = stored_credential(value)
        assert stored["last_backend_termination"] == termination
        assert stored["in_flight"] == {}
        record = json.loads(
            (value["root"] / "state/backend-observations.jsonl").read_text())
        assert record["kind"] == "slot_ended_idle"
        assert record["slot_id"] == 0
        assert record["claim_id"] == claim_a
        assert record["request_id"] == "request-1"
        assert record["binding"] == value["lease"]["expected_release_binding"]
        assert record["start"] == slot_states([(0, True), (1, False)])
        assert record["end"] == slot_states([(0, False), (1, True)])
        assert "private" not in json.dumps(record)
        assert "prompt" not in json.dumps(record)
        peer = json.loads(
            (value["root"] / "state/inference-proxy.json").read_text())
        assert set(peer["credentials"]["inference-2"]["in_flight"]) == {claim_b}
        attested = []
        released = {"state": "released", "lease_id": value["lease_id"]}
        with patch("ecosystem.inference_proxy.release_sequence",
                   side_effect=lambda root, lease, attestation, clock:
                   attested.append(attestation) or released):
            result = revoke_proxy_credential(
                value["root"], value["lease_id"], termination, lambda: 14.0)
        assert result["state"] == "revoked"
        assert attested[0]["kind"] == "sequence_end"
        assert attested[0]["binding"] == value["lease"]["expected_release_binding"]
        assert attested[0]["evidence_id"] == termination["evidence_id"]
        assert attested[0]["observed_monotonic"] == 13.0
        assert stored_credential(value)["state"] == "revoked"


def test_zero_or_two_start_flips_produce_no_slot_termination():
    cases = (
        ([(0, False), (1, False)], [(0, False), (1, False)],
         [(0, False), (1, False)]),
        ([(0, False), (1, False)], [(0, True), (1, True)],
         [(0, False), (1, False)]),
        ([(0, False), (1, False)], [(0, True), (1, False)],
         [(0, True), (1, False)]),
    )
    for pre_states, start_states, end_states in cases:
        with fixture() as value:
            claim_id, _secret = admit_with_slot_evidence(
                value, slot_states(pre_states), slot_states(start_states))
            assert _slot_ended_idle_termination(
                value["root"], value["lease_id"], claim_id,
                slot_states(end_states), lambda: 13.0) is None
            assert stored_credential(value)["last_backend_termination"] is None
            assert not (value["root"] /
                        "state/backend-observations.jsonl").exists()


def test_wrong_claim_or_mismatched_termination_fields_are_rejected():
    with fixture() as value:
        claim_id, _secret = admit_with_slot_evidence(
            value, slot_states([(0, False), (1, False)]),
            slot_states([(0, True), (1, False)]))
        assert _slot_ended_idle_termination(
            value["root"], value["lease_id"], "claim-missing",
            slot_states([(0, False), (1, False)]), lambda: 13.0) is None
        assert stored_credential(value)["last_backend_termination"] is None
    mutations = (
        lambda observation: observation.update(binding={"lease_id": "wrong"}),
        lambda observation: observation.update(request_id="wrong"),
        lambda observation: observation.update(claim_id="claim-wrong"),
        lambda observation: observation.update(observer_identity="wrong"),
        lambda observation: observation.update(clock_domain_id="wrong"),
        lambda observation: observation.update(observer_generation=0),
    )
    for mutate in mutations:
        with fixture() as value:
            claim_id, _secret = admit_with_slot_evidence(
                value, slot_states([(0, False), (1, False)]),
                slot_states([(0, True), (1, False)]))
            termination = _slot_ended_idle_termination(
                value["root"], value["lease_id"], claim_id,
                slot_states([(0, False), (1, False)]), lambda: 13.0)
            assert termination is not None
            forged = {key: item for key, item in termination.items()}
            mutate(forged)
            _finish_claim(value["root"], value["lease_id"], claim_id, True,
                          {"termination_observation": forged}, lambda: 13.0)
            assert stored_credential(value)[
                "last_backend_termination"] is None


def test_incarnation_drift_or_stale_slot_evidence_is_rejected():
    with fixture() as value:
        claim_id, _secret = admit_with_slot_evidence(
            value, slot_states([(0, False), (1, False)]),
            slot_states([(0, True), (1, False)]))
        drifted = slot_states([(0, False), (1, False)])
        drifted["identity"] = {**SLOT_IDENTITY, "pid": 99999}
        assert _slot_ended_idle_termination(
            value["root"], value["lease_id"], claim_id, drifted, lambda: 13.0) \
            is None
        assert not (value["root"] /
                    "state/backend-observations.jsonl").exists()
    with fixture() as value:
        claim_id, _secret = admit_with_slot_evidence(
            value, slot_states([(0, False), (1, False)]),
            slot_states([(0, True), (1, False)]))
        termination = _slot_ended_idle_termination(
            value["root"], value["lease_id"], claim_id,
            slot_states([(0, False), (1, False)]), lambda: 11.0)
        assert termination is not None
        _finish_claim(value["root"], value["lease_id"], claim_id, True,
                      {"termination_observation": termination}, lambda: 17.0)
        assert stored_credential(value)["last_backend_termination"] is None


def test_cancel_or_new_claim_supersedes_slot_termination():
    with fixture() as value:
        claim_id, _secret = admit_with_slot_evidence(
            value, slot_states([(0, False), (1, False)]),
            slot_states([(0, True), (1, False)]))
        cancel(value["root"], value["lease_id"], lambda: 12.5)
        assert _slot_ended_idle_termination(
            value["root"], value["lease_id"], claim_id,
            slot_states([(0, False), (1, False)]), lambda: 13.0) is None
        assert stored_credential(value)["last_backend_termination"] is None
        assert not (value["root"] /
                    "state/backend-observations.jsonl").exists()
    with fixture() as value:
        claim_id, secret = admit_with_slot_evidence(
            value, slot_states([(0, False), (1, False)]),
            slot_states([(0, True), (1, False)]))
        termination = _slot_ended_idle_termination(
            value["root"], value["lease_id"], claim_id,
            slot_states([(0, False), (1, False)]), lambda: 13.0)
        assert termination is not None
        _finish_claim(value["root"], value["lease_id"], claim_id, True,
                      {"termination_observation": termination}, lambda: 13.0)
        assert stored_credential(value)["last_backend_termination"] == termination
        admission = authorize_proxy_request(
            value["root"], {"authorization": "Bearer " + secret.hex(),
                            "request_id": "request-2"},
            body(request_id="request-2"), lambda: 14.0)
        assert admission["status"] == 200
        assert stored_credential(value)["last_backend_termination"] is None


def test_serve_one_connection_brackets_slot_observations_and_releases():
    with fixture() as value:
        secret = issue(value)
        identity = {**snapshot()["identity"], "total_slots": 2}
        def observed(states):
            return {"identity": identity,
                    "slots": [{"id": slot_id, "is_processing": state}
                              for slot_id, state in states]}
        timeline = []
        scripted = iter([observed([(0, False), (1, False)]),
                         observed([(0, True), (1, False)]),
                         observed([(0, False), (1, False)])])
        def fake_observe(_identity):
            timeline.append(list(events))
            return next(scripted)
        events = []
        backend, connection = e2e_plumbing(value, secret, events)
        with patch("ecosystem.inference_proxy.http.client.HTTPConnection",
                   return_value=backend), \
             patch("ecosystem.inference_proxy.backend_snapshot",
                   return_value={"identity": identity, "busy": False}), \
             patch("ecosystem.inference_proxy.observe_backend_slots",
                   side_effect=fake_observe):
            serve_one_connection(connection, value["root"], {
                "backend_base": "http://127.0.0.1:13305/v1"}, lambda: 11.0)
        assert timeline == [[], ["request", "getresponse"],
                            ["request", "getresponse", "read1"]]
        credential = stored_credential(value)
        assert credential["completed_requests"] == 1
        termination = credential["last_backend_termination"]
        assert termination is not None
        assert termination["terminated"] is True
        assert termination["request_id"] == "request-1"
        assert termination["binding"] == value["lease"]["expected_release_binding"]
        assert termination["observer_identity"] == "observer:inference-backend"
        assert termination["observed_monotonic"] == 11.0
        record = json.loads(
            (value["root"] / "state/backend-observations.jsonl").read_text())
        assert record["kind"] == "slot_ended_idle"
        assert record["slot_id"] == 0
        assert record["claim_id"].startswith("claim-")
        assert record["request_id"] == "request-1"
        assert record["evidence_id"] == termination["evidence_id"]
        assert record["end"] == observed([(0, False), (1, False)])


def test_serve_one_connection_without_start_flip_keeps_conservative_path():
    with fixture() as value:
        secret = issue(value)
        identity = {**snapshot()["identity"], "total_slots": 2}
        idle = {"identity": identity,
                "slots": [{"id": 0, "is_processing": False},
                          {"id": 1, "is_processing": False}]}
        calls = []
        def fake_observe(_identity):
            calls.append(1)
            return idle
        events = []
        backend, connection = e2e_plumbing(value, secret, events)
        with patch("ecosystem.inference_proxy.http.client.HTTPConnection",
                   return_value=backend), \
             patch("ecosystem.inference_proxy.backend_snapshot",
                   return_value={"identity": identity, "busy": False}), \
             patch("ecosystem.inference_proxy.observe_backend_slots",
                   side_effect=fake_observe):
            serve_one_connection(connection, value["root"], {
                "backend_base": "http://127.0.0.1:13305/v1"}, lambda: 11.0)
        assert len(calls) == 5
        credential = stored_credential(value)
        assert credential["completed_requests"] == 1
        assert credential["last_backend_termination"] is None
        assert not (value["root"] /
                    "state/backend-observations.jsonl").exists()


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(unittest.FunctionTestCase(function) for function in functions)
