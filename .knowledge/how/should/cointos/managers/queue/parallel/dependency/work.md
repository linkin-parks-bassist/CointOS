---
status: green
revised_at: "2026-09-29T08:03:04+10:00"
---

A steward surfaces at most one neglected project concern; it does not enumerate or queue the project's implementation graph. The manager owning that concern reads the project's current plan and contracts, identifies the next bounded frontier, and queues the currently-ready independent children together with explicit dependency edges. Independent chains should be simultaneously eligible so the scheduler can use available agents and lanes; genuine skeleton, test-contract, implementation and integration dependencies remain ordered.

A manager stage normally elaborates the next one to three concerns, not the whole project. It records the unexpanded remainder in the project plan and finishes; later managers expand subsequent frontiers. If only one node is actually ready, a linear thread is correct. If several unrelated nodes are ready but the manager queues only one without recording why, that is a planning-quality defect rather than steward policy.
