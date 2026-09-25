---
status: green
revised_at: "2026-09-14T22:40:40+10:00"
---

After spawning an isolated loopback OpenCode server but before creating/publishing its agent session or starting the attached run client, the supervisor reads /config and /provider with the exact directory query. verify_server_capacity requires auto-compaction enabled, the selected small/compaction model, an enabled compaction agent, and the expected transport baseURL. It finds exactly one Lemonade provider and requires its selected resolved model context/input/output limits to equal the launch record.

It then derives capacity again using the exact run executable and repository policy. Backend incarnation, effective context/output capacity and OpenCode version must still match the pre-server observation. Startup changes or missing/disagreeing facts raise ValueError. The supervisor finally stops any spawned server and closes its config fd; no attached agent prompt is started. A successful gate emits worker_capacity_verified with model, context/output allowance and client version, without credentials.

Resolved /provider limits are checked because writing a correct JSON config alone does not prove OpenCode loaded it. The installed 1.18.30 /doc confirms these routes. A real isolated server with the current live Qwen3.8 observation successfully read back 131072 context and 4096 output without any inference. Tests also inject stale resolved limits and changed incarnation. This is startup qualification; see when/must/opencode/capacity/be/requalified/during/a/session.md for its limits. Owners: ecosystem/opencode_launch.py verify_server_capacity/derive_capacity; scripts/opencode_observable.py main.
