---
status: green
revised_at: "2026-11-12T16:05:45+11:00"
---

The two-hour runtime-review Steward is paused under the user's factory-disable instruction. Its durable Coin wake f7f0d80f96f74769b7af6ff8b234773d remains in ~/.CointOS/state/coin/wakes with paused=true. Retain its record and waiting review task; do not resume it to fill idle GPU capacity. `factory_enabled: false` also prevents retained Stewards and their recovery/supervision from admission.

The retained schedule is `7 1-23/2 * * *` in Australia/Sydney, following daylight saving. Its Steward is cointos-runtime-review with standard/log tools. Its brief inspects the preceding four hours of logs/activity for Coin responsiveness, blockage, waste and scheduling, and dispatches a First Responder for concrete unowned problems. Routine findings stay internal. Explicit user reminders and other requested schedules remain available.

Only explicit resumption should re-enable this review. Factory admission must first be enabled; wakeups.pause(..., false) then resumes the schedule without replaying all missed occurrences. how/to/disable/the/cointos/factory.md owns the mode. Historical registration and first-run observations establish dispatch, not useful autonomous oversight.
