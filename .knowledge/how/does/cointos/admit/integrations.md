---
status: green
revised_at: "2026-10-07T07:25:05+11:00"
---

`spawner.integrations` admits at most one integration per enabled project at a time, for the project's oldest reviewed worker (`status == "review"`, not held, no active integration of its own). The integration ranks with `schema.KINDS["integrate"]["rank"]` and the project's priority.

An existing integration occupies its project's slot only while it can proceed: while it is running, or while it is waiting, not held (`spawner.held`: a kill hold or a held queue record) and its worker is in review. A held integration, or one waiting because its worker was revised or returned and is back at work, leaves the slot free for the project's other reviewed items, and its own worker never receives a second integration. When that worker returns to review, its existing integration resumes and refreshes its assignment for the new brief.

This prevents one stalled integration from halting every landing in a project; on 2026-10-06 a held, stale integration did exactly that for about six hours with `cointos check` green.

Proof:

```bash
cd "$(git rev-parse --show-toplevel)" && python3 -m unittest -q tests.test_revision.Revision.test_a_stalled_integration_does_not_block_the_projects_other_reviewed_items tests.test_revision.Revision.test_a_held_reviewed_item_is_not_integrated tests.test_revision.Revision.test_a_reviewed_item_under_integration_must_wait
```
