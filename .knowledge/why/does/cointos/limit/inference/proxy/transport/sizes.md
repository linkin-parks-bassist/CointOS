---
status: green
revised_at: "2026-09-26T04:21:25+10:00"
checked_at: "2026-09-20T14:29:43+10:00"
---

The proxy currently defaults request headers to 65,536 bytes, request bodies to 16,777,216 bytes, stream reads to 65,536-byte chunks, buffered completed JSON evidence to 8 MiB, and backend JSON observations to 1 MiB. Configuration repeats the header, body, and stream values. Header/body framing limits protect the hand-written HTTP parser, but no measured workload or protocol evidence has yet established whether these exact values admit every legitimate large-context agent request or backend observation. The limits must be compared with serialized maximum-context prompts, tool schemas, and backend health/model documents before retention or replacement with derived bounds.

The 8 MiB completed-JSON limit is *not* a response transport ceiling: `forward_proxy_response` sends each bounded chunk to the client before deciding whether to retain a copy for completion evidence. Once its buffer is full, it stops retaining, continues forwarding, and cannot infer `response_finished` from that JSON copy. `tests/test_inference_enforcement.py::test_json_response_larger_than_evidence_buffer_is_forwarded` covers forwarding beyond the evidence buffer. Do not raise the request ceiling merely to address this separate evidence limit.

A 2026-09-20 supervised probe confirmed that `ecosystem/inference.py` sends `json.dumps(body).encode("utf-8")` and `read_proxy_request` checks the received Content-Length against `body_bytes` before parsing; the proxy later re-serializes the parsed body with compact separators for the backend. Thus measurements must use the sender wire serialization, not only the shorter forwarded serialization. The worker attempted a local GGUF-vocabulary byte bound, but `/var/lib/lemonade/.cache` denied read access and the probe was stopped rather than escalating permissions or searching further. It produced no valid maximum-context measurement or evidence for changing the ceilings.

Blocker: No measured maximum legitimate serialized request or backend observation has been compared with the fixed byte ceilings; the private GGUF tokenizer path is unreadable to the worker.
Next check: Use readable representative OpenCode request/tool fixtures or an authorized tokenizer source to measure received-wire JSON sizes at admitted context, plus backend model/health payloads. Retain protocol-safe limits with headroom or derive them from admitted context and observed payloads.
