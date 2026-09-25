---
status: green
revised_at: "2026-09-14T23:33:30+10:00"
---

ecosystem/inference_proxy.py issue_proxy_credential locks workload, capacity and proxy state in that order. It requires a starting/active inference allocation and a registered active worker with a live PID/start tick identity. It generates one 32-byte secret, stores only its digest and the authoritative worker/sequence/run/model/context/output/release binding, delivers the raw secret once to a sink and refuses duplicate issuance. authorize_proxy_request authenticates the digest, rejects closing/revoked credentials or changed bindings, checks model/context/output and permits only one in-flight request per run before upstream I/O. The low-level ecosystem/inference.py request requires the lease and raw bytes, chooses the configured loopback proxy, sends bearer and lease/owner headers and encodes model/context/output directly from the allocation. It returns choices[0].message or a live response for stream mode. Missing allocation is an integration error in callers, not an ordinary user task prerequisite.
