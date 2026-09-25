---
status: green
revised_at: "2026-09-26T04:34:23+10:00"
---

After `authorize_proxy_request` records a 200 admission, `serve_one_connection` owns that exact claim until `_finish_claim` removes it. Request normalization, backend-base validation, optional backend observation, and HTTPConnection construction are preflight: a failure in any of them now calls `_finish_claim(root, lease_id, claim_id, False, {}, clock)` before returning an error. This prevents a pre-upstream failure from leaving the credential permanently in flight. Failures during forwarding also finish the claim as nonterminated, preserving the physical lease for later exact-evidence reconciliation rather than pretending the backend ended.

The proxy sends a JSON 400 only before the upstream response starts. Once `getresponse()` has succeeded and forwarding is entered, the connection is closed on an error without appending a second HTTP response to any already forwarded 200 bytes. This avoids corrupting the client wire response, but a midstream failure may still leave a truncated response and requires ordinary retry/reconciliation. `tests/test_inference_enforcement.py` has focused mocked tests for failed preflight claim cleanup and post-start response behavior. The application payload is installed under `/home/david/.CointOS`; existing services were not restarted, so a currently running process may still hold its prior module generation. Review this answer if `serve_one_connection` or its claim/response boundaries change.
