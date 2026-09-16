---
status: "unverified"
created_at: "2026-09-15T08:10:54+10:00"
scope: "local"
source: "Coordinator watchdog source implementation, existing7 checks and isolated tick smoke 2026-09-15"
updated_at: "2026-09-15T08:11:53+10:00"
---

ecosystem/watchdog.py tick serializes with state/watchdog.lock and periodically checks model/transport/job health and repairs missing verifier links. Before the current repair it did not call native reconcile_dead_callers, so caller-death cleanup required an explicit API invocation. Its generated review prompt also referenced retired checkout state paths even though state/conversations and logs live under cli.ROOT in the installed runtime. The periodic boundary can call native reconciliation before qualitative review and retain its summary in watchdog state; reconciliation preserves live/unknown callers and requires verified backend termination. Next check: implement the tick wiring and runtime-root prompt paths, then run existing watchdog/native checks without adding regression tests.

Implemented source: tick now invokes reconcile_dead_callers(cli.ROOT) under watchdog.lock before review and stores last_native_recovery on both review/idle paths. Review prompts use cli.ROOT/state/conversations and existing-check/direct-smoke MVP wording. Not installed. The guessed tests.test_watchdog module does not exist: the attempted combined run executed the16 native cases without assertion failures but failed module import. Existing watchdog references are in test_user_service_runtime_root, test_preemption, test_cumulative_usage, test_agent_task_path_portability and test_system_control; choose relevant actual owners rather than inventing a module. Next check: existing path/runtime checks and a bounded isolated tick smoke, then drained adoption.

Existing portability/runtime-root checks now pass7 cases after updating only stale expected path strings. A bounded isolated watchdog tick with a temporary runtime and no native records returns healthy and persists last_native_recovery.recovered=0. No new test cases were authored. The16 native cases also had no assertion failures in the earlier combined run; that overall command failed solely on a nonexistent watchdog test module. Source wiring is complete; live caller-death/restart qualification and installation remain pending.
