---
status: "unverified"
created_at: "2026-09-14T22:24:37+10:00"
scope: "local"
source: "David explicit design direction in conversation 2026-09-14; existing context-preparation contract inspected"
updated_at: "2026-09-14T22:25:18+10:00"
---

David's explicit direction on 2026-09-14 is to mostly scrap the existing roles and rebuild from nearly scratch, because much of their intended behavior is subsumed by general knowledge-tree machinery. This supersedes treating the existing role hierarchy as the target architecture; it does not assert that role files or runtime code have already been removed.

The dynamic parallel-agent design should therefore support durable agents with redesigned roles, shared knowledge-tree procedures, task-specific briefs, explicit authority and independent inference state. Any retained specialization needs a concrete behavior not already owned by knowledge-tree machinery. Agent identity, scheduling, inference residency, tool authority and independent verification remain separate design concerns even when static roles disappear.

Next design work: inventory existing role responsibilities, identify what is already owned by knowledge-tree procedures, and derive the minimal remaining agent/client contract alongside the full-context snapshot contract. Exact replacement behavior and an implementation sequence are not yet specified. Do not mechanically preserve the old roles in a new scheduler plan.

David clarification 2026-09-14: roles will still be needed. The intended change is a substantial shakeup of their responsibilities compared with the current written roles, not elimination of roles. Knowledge-tree machinery should own the general behaviors it subsumes; redesigned roles should express the remaining distinct responsibilities. The exact role set and boundaries are still to be designed.
