---
status: green
revised_at: "2026-09-26T03:10:28+10:00"
---

`scripts/opencode_observable.py` runs an attached CLI against a private OpenCode server. After the client exits without a semantic `step_finish`, `await_server_finish` mirrors any server-side continuation. Previously it polled session parts forever. A backend rejection can leave a new assistant message with `info.error`, no terminal `step-finish`, and `/session/status` empty: the server is idle, not continuing. Incident `20260925T162248Z-0` demonstrated this when Qwen3.5's strict template returned `System message must be at the beginning` before generating tokens; the survivor process stayed nominally running for minutes.

The source repair reads whole session messages and session status. It returns a nonzero outcome only when a *new* assistant message has an explicit error and the exact session is absent from the active-status map. It continues waiting while status reports `busy` or `retry`, and ignores historical assistant errors from before the current client attempt. It still accepts a fresh semantic `step-finish` first. A bounded direct smoke covered idle fresh error, active retry followed by stop, and historical error followed by stop; the two existing observable OpenCode checks passed. The wrapper was installed with source/installed file equality verified; no active worker was changed. A live recurrence after deployment remains unqualified, so retain the failure boundary as source-plus-bounded-smoke evidence rather than claiming a live error-path qualification.
