---
status: green
revised_at: "2026-09-14T22:40:40+10:00"
---

A launch record describes a particular backend incarnation, per-request allocation, client version and admitted allowance. Changing slots/context/KV layout, model/backend process, client version or selected inference/compaction model requires requalification. Startup read-back does not continuously observe every later request, and this implementation does not safely hot-update an existing OpenCode server's capacity beliefs.

Current operational rule: retain configuration for the qualified run; if it changes, pause and relaunch/resume through qualification rather than assuming the old cached model limits remain valid. Existing running sessions are not fixed retroactively by source changes. A future runtime guard must check allocation changes and prevent forwarding incompatible requests, preserving the durable session for recovery; it should not silently lower an agent's context merely because more agents exist. This is a remaining enforcement/design gap, not an implemented runtime monitor. No live model allocation was changed during this work.
