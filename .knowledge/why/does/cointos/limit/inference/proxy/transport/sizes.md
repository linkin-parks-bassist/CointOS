---
status: "unresolved"
created_at: "2026-09-16T17:25:59+10:00"
scope: "CointOS inference proxy transport"
source: "ecosystem/inference_proxy.py and config/model-policy.json inspected 2026-09-16"
checked_at: "2026-09-16T17:25:59+10:00"
blocker: "No measured maximum legitimate serialized request or backend observation has been compared with the fixed byte ceilings."
next_check: "Measure representative and maximum admitted prompt/tool JSON sizes plus backend model/health payloads; retain protocol-safe limits with headroom or derive them from admitted context and observed payloads."
---

The proxy currently defaults request headers to 65,536 bytes, request bodies to 16,777,216 bytes, stream reads to 65,536-byte chunks, buffered completed JSON to 8 MiB, and backend JSON observations to 1 MiB. Configuration repeats the header, body, and stream values. Header/body framing limits protect the hand-written HTTP parser, but no measured workload or protocol evidence has yet established whether these exact values can truncate legitimate large-context agent requests or observations. The limits must be compared with serialized maximum-context prompts, tool schemas, and backend health/model documents before retention or replacement with derived bounds.
