---
status: green
revised_at: "2026-11-09T15:56:41+11:00"
---

David proposes treating bugs as regressions by adding a characterizing failing test after discovery, then mapping the repair into CointOS's existing building workflow. This is user design direction from the Pigen counter discussion, not evidence of an implemented or dispatched automatic debugging flow.

The intended entry is a reproducible test of required correct behavior that fails on the current implementation. It characterizes the defect by exposing it; it must not assert the broken behavior as correct. The term regression here does not require proof that the behavior worked in an earlier revision. A failing test becomes a permanent guard against recurrence once fixed.

A suggested mapping is test authoring/acceptance, implementation against that binding test, and existing verification/review. The counter example motivates checking both compilation and generated behavior: making an emission error disappear alone does not establish a working counter. These mapping details are a discussion proposal; no new scheduler state, retry policy, operator dispatch, code change or deployment has been approved by this conversation.

This differs from correcting a defective accepted test contract. That implemented mechanism remains owned by how/does/cointos/correct/accepted/test/contracts.md; a new valid test exposing a product bug is not inherently a test correction.
