---
verified_at: '2026-09-12T01:52:04+10:00'
verified_by: opencode /home/david
scope: project local
source: current repository paths; pre-99318d9 Git history; ecosystem/models.py observe_opencode_backend_capacity
verification: Checked every named module and directory exists; used canonical architecture documents for responsibility grouping; confirmed the observation-adapter owner function in source.
review_when: Recheck after module moves, interface extraction, or a system-map reconciliation.
---

Start at the narrow owner for the concern; do not read all modules.

- Intake and task contracts: `ecosystem/cli.py`, `ecosystem/task_contracts.py`.
- Execution, continuation, and acceptance: `ecosystem/executor.py`,
  `ecosystem/continuation.py`, `ecosystem/verification.py`.
- Model facts and routing: `ecosystem/models.py`,
  `ecosystem/inference_policy.py`.
- Live OpenCode capacity record (pure derivation from fresh incarnation-bound
  evidence): `ecosystem/opencode_capacity.py`, tests
  `tests/test_opencode_capacity.py`.
- Version-qualified OpenCode capability (exact version -> observed output
  ceiling, checked-in catalogue): `ecosystem/opencode_client.py`,
  `config/opencode-capabilities.json`, tests `tests/test_opencode_client.py`.
- Fresh backend-capacity observation adapter (incarnation-bound projection of one
  verified resident observation into the capacity constructor's record):
  `ecosystem/models.py` `observe_opencode_backend_capacity` (reuses
  `_observed_model_record` and `context_layout.observed_context_layout`), tests
  `tests/test_model_admission.py` and `tests/test_context_layout.py`.
- Physical inference admission and proxying: `ecosystem/inference_capacity.py`,
  `ecosystem/inference_proxy.py`, `ecosystem/inference.py`.
- Host/resource and worker ownership: `ecosystem/resource_control.py`,
  `ecosystem/workload_control.py`, `ecosystem/execution_budget.py`.
- Contact and conversation: `ecosystem/telegram.py`, `ecosystem/control_turns.py`,
  `ecosystem/control_worker.py`, `ecosystem/control_agent.py`,
  `ecosystem/conversation.py`, `ecosystem/presentation.py`,
  `ecosystem/notifier.py`.
- Model-independent survival plane: `survival/`, especially `gateway.py`,
  `guardian.py`, and `lifecycle.py`.
- Launch/configuration adapters: `scripts/`, `services/`, and `config/`.
- Matching tests: `tests/test_<owner>.py`; process-level survival checks are under
  `tests/integration/`.

Use `what/is/architecture/of/cointos.md` for flow and
`what/is/current/technical_debt.md` for known boundary debt. Confirm an exact
function/interface in source before changing it.
