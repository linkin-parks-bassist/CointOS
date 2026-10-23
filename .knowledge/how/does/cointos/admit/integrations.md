---
status: green
revised_at: "2026-10-16T06:38:24+11:00"
---

New and retained admission through spawner.integrations/runnable admits at most one integration per enabled project at a time. A new reviewer takes the oldest eligible reviewed worker: status review, not held, with any owned queue item ready and no retained integration of its own. Readiness includes pending independently reviewed test corrections. Integration rank combines schema.KINDS["integrate"]["rank"] and project priority.

An existing integration occupies its project's slot while running, or while waiting without an integration hold and its worker is review-ready. A held integration, a worker revised/returned to construction, or a waiting consumer review blocked on a test correction leaves the slot available to other eligible reviews. In particular, the consumer cannot prevent its correction from being reviewed. Existing running reviews retain ordinary lifecycle handling.

Retained integrations prevent duplicate reviewers for their workers even while ineligible. When the worker becomes review-ready again, its integration can resume, refreshing its assignment for a changed brief. Resuming a held integration waits while another review in the same project runs; other projects remain independent.

This prevents stale reviews from halting a project. A held integration caused roughly six hours of blocked landings on 2026-10-06 despite green runtime checks. Production-function and real-Git regressions now cover held/revised workers, retained ownership, serialization and correction-first review eligibility.

Proof:

```bash
cd "$(git rev-parse --show-toplevel)" && python3 -m unittest -q tests.test_revision.Revision.test_a_stalled_integration_does_not_block_the_projects_other_reviewed_items tests.test_revision.Revision.test_a_held_reviewed_item_is_not_integrated tests.test_revision.Revision.test_a_reviewed_item_under_integration_must_wait tests.test_packet_corrections.Corrections.test_waiting_consumer_review_cannot_occupy_the_correction_review_slot tests.test_pipeline_simulator
```
