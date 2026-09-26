---
status: "green"
revised_at: "2026-09-26T10:28:49+10:00"
---

Status: in progress

Add focused tests for the autonomy-loop controls, which are committed (`3de41df`, `e888d61`) but untested.

**What to cover:**
- `ecosystem/cli.py::emergency_stop()`: it creates `state/PAUSED`, cancels active autonomous (`spawner:`) jobs, and spares `sole_survivor` and David's user-directed jobs unless `include_user_work=True`.
- `ecosystem/cli.py::halt()`: it creates `state/PAUSED`, calls `systemctl --user stop` for timers/paths before `agent-*`, and still returns when model unload raises. Patch `subprocess.run` and `resource_control.unload_all_models`; never stop real units in a test.
- `ecosystem/backend_profile_scheduler.py::assess_profiles`: with `profile_minimum_parallel_sequences: 2`, an idle one-lane work model with no demand plans growth to two lanes. The value is capped by the qualified ceiling.
- `ecosystem/spawner.py::_candidate`: urgent before queued before drafted, cooldown and active-job skips, then survey, then steward.

Use temporary roots, as existing tests do. Commit only the new test files; do not stage unrelated working-tree changes.

**How to tell it is done.** `python3 -m unittest discover -s tests -q 2>&1` passes with the new tests counted (baseline 837). Follow `how/to/test/cointos_changes.md`: function-style tests need `load_tests` adapters, or discovery silently skips them.
