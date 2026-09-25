---
status: green
revised_at: "2026-09-20T03:47:13+10:00"
---

The existing tests/test_parent_reservation_persistence.py module documents an expected RED composition-readiness regression: execute_next caches a parent job, cli.enqueue_child durably reserves 300 task_seconds during launch, then a cached parent write-back can clobber the reservation. It failed at line 139, `assert execute_next() is True`, before reaching that assertion.

Root cause: commit 232a2d6 (observe worker leases and reroute realized models) added a post-realization convergence gate to execute_next that defers with "post-realization route has not converged on the realized model" when decision["model"] != realization["model"]. The test's fake realize returned {"state": "realized"} with no model key, so "test-model" != None and the harness deferred before launch. The failure was unrelated to the authority-policy rename, whose only test diff was the imported helper name.

Repair: the fake realize now returns {"state": "realized", "model": "test-model"}, matching the real realize contract (ecosystem/models.py:1055+ returns a "model" key). No executor change was needed: the durable-reservation fix already exists from commit 1f445d5, an ancestor of test commit c69d1ac. _adopt_durable_reservation_state (ecosystem/executor.py:1296) re-adopts durable remaining_budget and child_reservations before the cached write-back, via _persist_parent_job (executor.py:1321) at the pre-close and final write-back sites (~1648, 1768, 1776).

Evidence: disabling _adopt_durable_reservation_state temporarily made the test RED on the exact documented loss (remaining_budget.task_seconds=600, expected 300); the executor was restored byte-identical (md5 verified). Green: tests.test_parent_reservation_persistence 1/1, tests.test_mvp_task_contracts 9/9, tests.test_preemption 4/4, py_compile OK on both touched files.