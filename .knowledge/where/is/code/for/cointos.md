---
status: green
revised_at: "2026-09-26T03:36:47+10:00"
---

Start at the narrow owner for the concern; do not read all modules.

- Intake and task contracts: `ecosystem/cli.py`, `ecosystem/task_contracts.py`.
- Execution and acceptance: `ecosystem/executor.py`, `ecosystem/acceptance.py`,
  `ecosystem/verification.py`. The plain `run_finished` completion path calls
  `acceptance.artifact_failure` for deterministic contract checks; the executor
  alone applies the resulting job transition to state
  `failed` with a clear `error` reason when a declared `kind == "artifact"` item is
  missing, empty, or has no explicit path; verifier, command/handoff kinds, and
  exact-session continuation are untouched. OpenCode owns active context compaction;
  `ecosystem/continuation.py` is a deferred experiment disconnected from execution.
  Regression tests: `tests/test_opencode_compaction.py`.
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
- One ephemeral OpenCode configuration encoder (writes the validated effective
  record's limits to an anonymous memfd, stripping static capacity claims):
  `ecosystem/inference_proxy.py` `opencode_environment`, base catalogue
  `config/executor-opencode.json` (names only, no limits), tests
  `tests/test_inference_enforcement.py`.
- Final pre-spawn managed-launch capacity validation (derives the effective record
  for the routed model and fails the job back to `ready` on any disagreement, no
  spawn or inference request): `ecosystem/executor.py` `launch_runner_round`
  `capacity_preflight` phase + `_validate_worker_capacity` (mockable
  `observe_capacity`/`qualify_capability`/`capacity_policy` producers with
  fail-closed defaults), the pure lease-vs-record check
  `ecosystem/inference_capacity.py` `validate_launch_capacity`, checked-in policy
  `config/opencode-capacity.json`, tests `tests/test_executor.py` and
  `tests/test_inference_capacity.py`.
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
- Launch/configuration adapters: `scripts/`, `services/`, and `config/`. Read-only installed health/lease projection: `scripts/cointos-health` (PATH link from `scripts/install-cointos`); it does not mutate resource control.
- Matching tests: `tests/test_<owner>.py`; process-level survival checks are under
  `tests/integration/`.

Use `what/is/architecture/of/cointos.md` for flow and
`what/is/current/technical_debt.md` for known boundary debt. Confirm an exact
function/interface in source before changing it.

Observable direct/manual launch qualification and server read-back: `ecosystem/opencode_launch.py`, invoked by `scripts/opencode_observable.py` before session/client creation. Tests: `tests/test_opencode_launch.py` include stale config, admitted allowance, startup mismatch/change, no-inference real-server read-back and inert real-client request capture. `constrain_launch_capacity` in `ecosystem/inference_capacity.py` supplies encoder allowances that fit both the lease and the live backend.
