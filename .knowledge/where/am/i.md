---
status: green
revised_at: "2026-09-26T08:01:23+10:00"
---

This is `/home/david/Projects/CointOS`, David's personal, local-only CointOS orchestration repository. It turns local/Telegram requests into durable agent work, coordinates local inference and survival controls, and stores its implementation, configuration, tests, plans, specifications, decisions, and agent-facing knowledge. Do not mix professional, partner, or customer information into it.

Source lives primarily in `ecosystem/` and `survival/`; launch adapters are in `scripts/` and `services/`; policy/configuration is in `config/`; standard-library tests are in `tests/`. Start current project work with `what/is/the/spec.md`, `what/is/the/plan.md`, `what/is/the/state.md`, and `what/is/next.md`; detailed orientation continues through `what/is/current/project_priority.md`, `where/is/code/for/cointos.md`, and `what/is/architecture/of/cointos.md`.

Mutable runtime data is physically under `/home/david/.CointOS`, not this checkout. There are intentionally no repo compatibility paths for `state/` or `logs/`. The proxy, Telegram/control, notifier, resource guard, and watchdog run from the installed prefix. At the latest check, incident `20260925T162248Z-0` had been recovered by an explicitly requested operator action; resource mode was normal and the durable work gate was open. Both Sole Survivor attempts had failed required-artifact acceptance before recovery. This is temporary operational state: establish current truth through `where/is/runtime_truth.md` and `what/is/the/state.md`, and use `how/to/test/cointos_changes.md` before claiming verification.

The canonical branches cover procedures in `how/` (for example `how/to/operate/cointos.md`), requirements and state in `what/` (`what/is/intended/agent_scheduling.md`), locations in `where/` (`where/is/runtime_truth.md`), and rationale in `why/` (`why/does/cointos/limit/inference/proxy/transport/sizes.md`). The `does/` branch holds behavior yes/no claims, such as `does/cointos/recovery/preserve/a/close-intent/job/owned/by/an/exact/live/executor.md`; `is/` is reserved for classification yes/no answers.

Agent policy is indexed by `global:how/to/behave.md`; project-specific requirements and operational policy are in this tree’s spec and intended-behavior leaves.
