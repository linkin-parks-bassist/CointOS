---
status: green
revised_at: "2026-11-17T05:45:21+11:00"
---

`TypeError: Can only get item pairs from a mapping` during a tool-history request comes from the Flash-Next Jinja template iterating `tool_call.arguments|items`. OpenAI/OpenCode histories serialize function arguments as JSON strings, while this template needs decoded objects. Initial tool generation can pass even though the next request fails when it replays that assistant tool call.

backend_halogen.render normalizes each assistant tool call at the rendering boundary: decode string arguments with json.loads, require a dict, preserve call IDs and tool-result messages, and construct new message/call/function mappings so authoritative client history is not mutated. Non-object or malformed arguments fail clearly before native rendering. Other native backends retain their own contracts.

The live fix reproduced the exact original failure on synthetic unnormalized history, passed native render with normalized history, and returned TOOL ROUNDTRIP OK through /v1/private/chat/completions with a string-argument assistant call followed by its tool result. Evidence: ~/.local/state/halogen-trial/tool-history-fix.json; it contains only synthetic data and no bearer key. The daemon replacement preserved the same Halogen container and engine PID. Runtime health checks passed. Existing client histories need not be cleared; retrying uses the corrected adapter.

Tests in tests/test_backend_halogen.py cover nested typed argument decoding, unchanged call-result identity and input history, and refusal of non-object arguments. The focused backend/snapshot suite passes 63 tests. patches/halogen/qualify.py includes tool-history continuation in addition to tool generation, interleaved token continuity and lost-state refusal. Do not treat a generated tool call alone as qualification of its round trip.
