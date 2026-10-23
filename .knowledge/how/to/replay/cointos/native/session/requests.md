---
status: green
revised_at: "2026-10-19T20:00:35+11:00"
---

Replay the actual OpenCode request before attributing a restart cache miss to native inference. Keep session exports and token vectors private; they contain conversation and product material.

Use an isolated XDG config/data/state/cache root and the installed CLI to import a regular JSON export with `opencode import <file> --pure`. Preserve original provider/model IDs: changing them can remove historical reasoning from the SDK echo. Use the original-user resume hook to avoid adding a new user turn. Point the private provider at a stub returning plain text without tool calls, and install a tool-execution guard. Never direct this replay at the live model gateway or production session database.

Capture the real SDK body. Reconstruct gateway preparation with the task's pinned system prefix, tool contracts, reasoning effort and effective budget. Verify model signature, cached conversation digest, result IDs and canonical token count against the failed request. CPU-only native render/tokenize/read can then compare the held vector, canonical mismatch position, preserved prefix, literal native suffix and reader. Check refusal of changed history/contracts, missing or duplicate results, unsupported user fields or structured content, and new calls. Text user messages after completed results can retain verified history only when the native closing prefix still matches; test templates that remove earlier reasoning on a new user turn. This qualifies request construction and splicing, not GPU state restoration or speed.

OpenCode 1.18.35's private import can leave an EffectFlock heartbeat after its process exits. Its stale threshold is 60 seconds, so a 45-second bootstrap timeout is inconclusive. Verify the departed private PID and allow native lease handling; do not delete live locks or weaken host protections.

The private workflow-observation-20261019/replay_restart_sdk.py harness and sdk-restart-6bu6ahw0/result.json reproduce the 103,095-token request. restart-continuation-replay.json checks the installed helper against it. Cache-retention and native-reply owners hold outcomes and qualification limits; the global OpenCode export procedure owns safe export mechanics.
