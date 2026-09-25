---
status: green
revised_at: "2026-09-26T01:31:22+10:00"
---

The source and installed timeout policy is `config/time.cfg`, read by `ecosystem.time_policy`. Its inference section currently sets `model_start_deadline_seconds = 180` and `model_stop_deadline_seconds = 15`; `ecosystem.resource_control._seconds("inference", KEY)` is the existing consumer used by model load/unload requests. A separately supervised backend-profile oneshot must allow more than both operations plus verification/retry overhead; a default systemd 90-second start timeout would not cover a permitted 180-second load. Evidence: source `config/time.cfg`, `ecosystem/time_policy.py`, and `ecosystem/resource_control.py` checked 2026-09-26.
