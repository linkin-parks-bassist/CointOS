---
status: green
revised_at: "2026-09-26T09:03:07+10:00"
---

This is `/home/david/Projects/CointOS`, David's personal, local-only CointOS repository: an autonomous agent ecosystem that schedules local-model agents onto the GPU (definition: `what/is/cointos.md`). It stores its implementation, configuration, tests, plans, specifications, decisions, and agent-facing knowledge. Do not mix professional, partner, or customer information into it.

Source lives primarily in `ecosystem/` and `survival/`; launch adapters are in `scripts/` and `services/`; policy/configuration is in `config/`; standard-library tests are in `tests/`. Start with `what/is/cointos.md`, then `what/is/the/spec.md`, `what/is/the/plan.md`, `what/is/the/state.md`, and `what/is/next.md`; detailed orientation continues through `what/is/current/project_priority.md`, `where/is/code/for/cointos.md`, and `what/is/architecture/of/cointos.md`.

Mutable runtime data is physically under `/home/david/.CointOS`, not this checkout. There are intentionally no repo compatibility paths for `state/` or `logs/`. The proxy, Telegram/control, notifier, resource guard, and watchdog run from the installed prefix. Establish current operational truth through `where/is/runtime_truth.md` and `what/is/the/state.md`, and use `how/to/test/cointos_changes.md` before claiming verification.

The canonical branches cover procedures in `how/` (for example `how/to/operate/cointos.md`), requirements and state in `what/` (`what/is/intended/agent_scheduling.md`), locations in `where/` (`where/is/runtime_truth.md`), and rationale in `why/` (`why/does/cointos/limit/inference/proxy/transport/sizes.md`). The `does/` branch holds behavior yes/no claims, such as `does/cointos/recovery/preserve/a/close-intent/job/owned/by/an/exact/live/executor.md`; `is/` is reserved for classification yes/no answers.

Agent policy is indexed by `global:how/to/behave.md`; project-specific requirements and operational policy are in this tree’s spec and intended-behavior leaves.
