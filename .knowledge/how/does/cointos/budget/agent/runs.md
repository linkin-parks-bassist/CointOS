---
status: green
revised_at: "2026-10-23T20:49:46+11:00"
---

Tasks pin generation_seconds and generation_tokens from the configured common defaults, optional recovery.role_budgets and explicit task overrides, in that precedence order. Current source and installed defaults are 86,400 charged generation seconds or 2,000,000 generated tokens, with an empty role_budgets map: managers and Operators have no shorter configured allowance. Configuration edits do not rewrite existing tasks.

schema.spent charges generated time/tokens and granted Operator budgets. Waits, prefill and tools do not consume that budget. Either limit ends a run. warning_fraction sends one wrap-up warning within the remaining allowance; launch reports the effective limits, reasoning cap and fresh-retry allowance.

The budget control sets waiting/undispatched limits and permits explicit monotonic increases for running tasks outside validation. It refuses live decreases, settled tasks and invalid inputs. An increase updates task and queue metadata while preserving generation already spent, grants, session, run count and artifacts; it notifies the task and re-arms its warning.

Workers, managers, integrators and Operators have zero automatic fresh budget retries through recovery.role_fresh_retries. Transport/process interruption recovery is distinct and retains sessions. Failed work reaches one eligible recovery controller per assignment/version; exhaustion does not create recursive controllers or reset spend. Changed authorised assignments can be revised through the normal controls; unchanged work does not receive a free refill.

A checked handoff, recovery replacement or recovery test correction transfers work atomically with the controller's completion. Budget size does not establish correctness, acceptance or useful unattended progress.

Evidence: schema.budget and schema.spent, tasks.set_budget, recovery configuration in source and installed config/cointos.json, and the handoff/replacement contracts. These are implementation facts; changing numerical policy requires current user authority.
