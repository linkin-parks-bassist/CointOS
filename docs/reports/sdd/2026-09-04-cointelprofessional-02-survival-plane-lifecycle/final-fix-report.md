# Plan 2 survival-plane final-fix report

Author: Noether (`/root/plan2_final_fix`)

Date: 2026-09-05

Reviewed base: `ae8c2752a5f468267d9627dcd624d89055598b00`

Implementation commit: `1a27928534b0311341f907a192022214106f7349`

Status: **DONE_WITH_CONCERNS**

## Outcome

All six Critical, six Important, and one Minor findings in
`final-review-result.md` were verified against the reviewed implementation and
repaired where technically valid. The successful route is now the production
composition: pure lifecycle effects are interpreted by a complete adapter table,
literal systemd/HTTP/filesystem fingertips remain injectable, and tests exercise
both `RESTART` and `RESET` through that constructor. No service was installed,
enabled, stopped, restarted, or otherwise mutated, and no credential or Telegram
endpoint was accessed.

The only concerns are evidence-environment limits, not known implementation
defects: this checkout has no installed `cointelprofessional` account, passwordless
root is unavailable, and unprivileged user namespaces are disabled, so a real
two-UID filesystem execution could not be run here. The installer trace, exact
mode/ownership contract, immutable source/delivery split, real Unix peer credential
test, and same-UID operation tests are green. Actual installed-UID and live
Telegram/systemd acceptance remains the explicitly prohibited Plan 5 gate.

## Finding closure

### Critical 1 — incomplete production adapter graph

- Verification: valid. The reviewed `production_adapters()` supplied only system
  and user unit adapters while the reducer required seven direct effects.
- Repair: `production_adapters()` now constructs and validates the exact complete
  adapter keyset for notification, admission closure, checkpoint, reconciliation,
  verification, resume, finish, system/user control, and bounded waits. Direct
  adapters publish runtime snapshots, checkpoint requests, pause state, completion
  records, and root-owned critical messages. Required installed units are checked
  during production construction; missing units fail initialization.
- Files: `survival/system_control.py`, `survival/guardian.py`,
  `config/survival-lifecycle.json`, `scripts/install-survival-plane`, and the
  guardian service.
- Coverage: `test_production_constructor_is_complete_and_drives_both_commands`,
  `test_catalog_has_semantic_stages_and_excludes_survival_units`,
  `test_load_config_rejects_missing_or_noncanonical_uid`, and
  `test_status_distinguishes_an_uninstalled_required_unit`.

### Critical 2 — no autonomous lifecycle recovery

- Verification: valid. Socket acknowledgement preceded the durable acknowledged
  reduction, idle startup performed no scan, and failures had no blocked owner.
- Repair: the guardian commits `ack_committed` and its pending effect before the
  socket response. Startup and every bounded idle poll resume the oldest incomplete
  lifecycle. Requests are serialized by durable Telegram update order. Effect
  failure reduces to `blocked`, emits one direct critical intent, and later idle
  recovery retries the retained idempotent effect. Each external action is preceded
  by persisted pending state; each successful action is followed by an immutable
  atomic result before reducer state advances.
- Files: `survival/guardian.py`, `survival/lifecycle.py`, and
  `survival/system_control.py`.
- Coverage: `test_guardian_commits_pending_work_before_the_socket_response`,
  `test_disconnected_response_peer_leaves_durable_recoverable_work_and_continues`,
  `test_idle_recovery_advances_an_accepted_request_without_telegram_replay`,
  `test_oldest_blocked_request_serializes_later_lifecycle_commands`,
  `test_every_success_path_effect_recovers_after_external_action_before_result_commit`,
  and `test_every_verified_effect_result_survives_death_before_state_reduction`.

### Critical 3 — flat unsafe lifecycle semantics

- Verification: valid. The flat unit set could not preserve dependency roles,
  prior pause/activity, hard reset escalation, configured deadlines, or activation
  gating.
- Repair: a strict root-owned catalogue classifies activation sources, inference
  prerequisites, control services, ordinary services, and intentionally inactive
  units. Admission snapshots prior activity and pause state. Activation is stopped
  first; `RESTART` publishes a David-readable checkpoint request and waits the
  configured grace before recording survivors interrupted; `RESET` records
  interruption before its durability fence and proceeds immediately. Stop,
  `SIGTERM`, `SIGKILL`, reset-failed, start, active state, and cgroup-empty
  postconditions are explicit fixed-argv operations. An absent ControlGroup on an
  inactive unit is represented as verified empty. Lemonade and model start/stop,
  grace periods, reconciliation, and model canary all consume central policy.
  Blocking subprocesses and health probes renew the guardian watchdog. The health
  gate keeps activation and ordinary execution closed, restores only prior active
  units, preserves prior pause, and returns a temporarily started inference service
  to inactive when that was its prior state. `ProtectHome=read-only` lets the tightly
  scoped `ReadWritePaths` state exception and user manager bus remain reachable.
- Files: `config/survival-lifecycle.json`, `survival/system_control.py`,
  `survival/lifecycle.py`, `services/system/cointelprofessional-guardian.service`,
  and `docs/operations.md`.
- Coverage: `test_lifecycle_effects_map_only_to_legal_allowlisted_systemctl_calls`,
  `test_escalation_observes_configured_terminate_and_kill_grace`,
  `test_reset_failed_uses_exact_allowlisted_systemctl_argv`,
  `test_inactive_unit_with_no_realized_cgroup_is_verified_empty`,
  `test_watchdog_runner_pulses_during_a_bounded_external_probe`,
  `test_production_route_restores_an_initially_inactive_inference_service`, the
  pause-gate reducer tests, and the production-constructor ordering assertions.

### Critical 4 — unsupported Telegram update poisons polling

- Verification: valid. Body parsing occurred before an offset-owning disposition,
  so legitimate non-message updates could restart-loop forever.
- Repair: update identity is decoded independently. Every identified unsupported
  callback, channel post, edited message, or non-message body gets an exact durable
  `ignored` disposition before the durable poll offset advances. `allowed_updates`
  requests only messages as a first filter without weakening the defensive path.
  The offset is reloaded on worker restart. Malformed HTTP-200/non-JSON and API
  `ok:false` responses remain explicit upstream failures rather than false success.
- Files: `survival/gateway.py` and `survival/telegram_api.py`.
- Coverage: `test_unsupported_update_is_disposed_and_later_command_is_received`,
  `test_all_identified_non_message_shapes_are_disposed_and_offset_survives_restart`,
  `test_get_updates_exercises_https_long_poll_through_injected_exchange`, and
  `test_http_200_non_json_response_is_explicit_failure`.

### Critical 5 — cross-UID permission directions were inverted

- Verification: valid. The shared writable store root and mutable critical records
  allowed ordinary work to replace survival namespaces and spoof root messages;
  root-created critical state also lacked a sound gateway update path.
- Repair: the store root is `root:root 0755`. Gateway-owned private state is `0700`.
  The gateway-to-agent inbox is `cointelprofessional:agent_ecosystem_io 2750` with
  `0640` records, giving David read but not directory write. The root-to-gateway
  critical directory is `root:cointelprofessional 2750` with immutable-to-gateway
  `0640` source records. Gateway delivery state lives separately under its own
  private directory. Root lifecycle state is `0700`; the policy projection is
  root-owned and group-readable. David receives only the spool group; the gateway
  receives only the private command group. Socket authorization still requires the
  exact configured numeric peer UID, not group membership. Service write paths are
  split by direction.
- Files: `scripts/install-survival-plane`, `survival/records.py`,
  `survival/telegram_api.py`, both service units, and the guardian socket unit.
- Coverage: `test_installer_realizes_exact_snapshot_modes_paths_and_dynamic_uids`,
  `test_guardian_critical_message_is_group_readable_but_immutable_to_gateway`,
  `test_shared_atomic_json_has_final_mode_before_publication`,
  `test_permission_failure_leaves_no_published_or_temporary_record`, the real Unix
  `SO_PEERCRED` tests, and the forbidden-unit/peer tests. The installed two-UID
  execution limitation is recorded under Concerns below.

### Critical 6 — quarantine disabled the gateway forever

- Verification: valid. Durable quarantine presence was incorrectly used as a
  permanent process-liveness veto.
- Repair: worker/process health is now only fresh successful poll and egress loop
  observations. One malformed inbox, critical source, or delivery record is
  best-effort isolated and scanning continues. Failed quarantine moves are also
  nonfatal and reported truthfully. Every incident has a durable gateway-owned
  health record; the guardian scans all incident facts and creates one deduplicated
  root critical intent per incident, so several records found in one scan are not
  collapsed into the latest incident. Quarantine remains visible data degradation
  without suppressing watchdog renewal or contact.
- Files: `survival/gateway.py`, `survival/telegram_api.py`,
  `survival/system_control.py`, and `scripts/install-survival-plane`.
- Coverage: `test_quarantine_degrades_data_health_without_stopping_egress_heartbeat`,
  `test_unmovable_malformed_record_does_not_withhold_egress_heartbeat`,
  `test_unmovable_quarantine_incident_is_deduplicated_and_visible`,
  `test_guardian_reports_each_gateway_quarantine_incident_once`, and
  `test_guardian_reports_every_gateway_incident_even_when_scans_find_several`.

### Important 1 — acknowledgement deadline applied to the wrong transport

- Verification: valid. Only guardian socket acknowledgement used the two-second
  policy; Telegram acknowledgement inherited the general forty-second timeout.
- Repair: production constructs a distinct acknowledgement sender using
  `command_acknowledgement_deadline_seconds` and wraps it in an overall wall-clock
  deadline, not merely a per-socket timeout. Guardian framed acknowledgement also
  recomputes the absolute remaining deadline for connect, send, header, and payload.
  Timeout, connection reset, Telegram `ok:false`, and a false return all durably move
  `ready -> sending -> delivery_unknown`; command processing remains accepted.
- Files: `survival/gateway.py` and `survival/telegram_api.py`.
- Coverage: the acknowledgement sending/exception/API-rejection tests,
  `test_acknowledgement_deadline_is_an_overall_wall_clock_bound`,
  `test_production_acknowledgement_adapter_uses_command_deadline`, and
  `test_guardian_acknowledgement_deadline_bounds_a_dribbling_frame`.

### Important 2 — monotonic deadline invalid after reboot

- Verification: valid. A persisted monotonic value had no clock-epoch identity.
- Repair: inbox records carry the accepting kernel boot ID. Only matching known boot
  identities permit a future monotonic comparison; a changed or unavailable boot ID
  makes the degraded response immediately due. Boot-ID read failure is contained in
  both poll and egress workers. All persisted and live numeric observations reject
  booleans, NaN, and infinities before egress.
- Files: `survival/gateway.py` and `survival/telegram_api.py`.
- Coverage: `test_rebooted_monotonic_deadline_is_immediately_due`,
  `test_boot_id_read_failure_does_not_crash_poll_or_egress`, and
  `test_nonfinite_persisted_deadline_is_quarantined_before_egress`.

### Important 3 — timing policy had no coherent installed owner

- Verification: valid. Gateway-local subset parsing, guardian hard-coding, and an
  editable file inside the content-addressed release created multiple owners.
- Repair: `survival/time_policy.py` is the strict schema/seconds/reload owner;
  `ecosystem/time_policy.py` delegates to it. The editable root-owned
  `/etc/cointelprofessional/time.cfg` is outside releases and preserved on updates.
  The guardian atomically publishes group-readable last-known-good `policy/time.json`;
  invalid edits retain it, persist rejected status, and create a deduplicated direct
  report. Gateway and guardian reload the whole projection; gateway workers, send
  closures, and supervisor heartbeat-age checks all consume their locally adopted
  complete value. A gateway restart can use the guardian LKG and continues to report
  an invalid mutable source as rejected.
- Files: `survival/time_policy.py`, `ecosystem/time_policy.py`, both production
  modules, installer, services, and `docs/operations.md`.
- Coverage: all `tests/test_time_policy.py` tests,
  `test_production_gateway_live_reload_adopts_complete_policy_and_retains_invalid_edit`,
  `test_gateway_restart_uses_guardian_last_known_good_when_mutable_source_is_invalid`,
  `test_guardian_live_policy_reload_persists_rejection_and_keeps_last_known_good`,
  and `test_gateway_supervisor_applies_live_heartbeat_age_policy`.

### Important 4 — first-install publication was partial after commit

- Verification: valid. `current` became visible before stable unit wrappers existed.
- Repair: all stable unit links are validated and created while deliberately
  dangling; every service/code/config/document path resolves through the one
  authoritative `current` symlink. Only the atomic `current` rename publishes a
  usable surface. Retry removes unreferenced candidates and completes idempotently.
- Files: `scripts/install-survival-plane` and production unit paths.
- Coverage: `test_first_install_interruption_at_each_wrapper_keeps_authoritative_root_absent`,
  initial/pre-commit/commit/post-commit failure tests, and installer idempotence and
  tamper-detection tests.

### Important 5 — torn append journal could poison prior results

- Verification: valid. Every JSONL line had to decode before a prior successful
  result could be used.
- Repair: each effect attempt is an exclusive, complete JSON file in a per-effect
  directory. A malformed/torn attempt is quarantined independently; an earlier
  verified result remains usable and suppresses external action replay.
- Files: `survival/system_control.py` and `survival/records.py`.
- Coverage: `test_atomic_result_records_isolate_a_torn_attempt_tail`,
  `test_durable_verified_result_is_written_before_reducer_completion_and_recovers`,
  and the every-effect crash-cut tests.

### Important 6 — evidence exercised a fictional route

- Verification: valid. The reviewed guardian-success graph injected direct adapters
  absent from production.
- Repair: production construction is asserted to contain the exact adapter set and
  is used to complete both commands with only literal external managers/probes
  injected. Tests inspect operation order, pause/active restoration, durable jobs,
  completion, critical intents, activation exclusion, inactive resource guard,
  cgroup postconditions, and both backend/model PID turnovers using real disposable
  process groups. Socket/process/systemd/installer integration remains separate.
- Files: `tests/test_system_control.py`, `tests/test_survival_guardian.py`, and
  `tests/integration/test_survival_processes.py` plus their production modules.
- Coverage: `test_production_constructor_is_complete_and_drives_both_commands`,
  `test_production_route_turns_over_disposable_real_process_groups`, recovery and
  reconciliation tests, real socket/peer tests, and the installer integration suite.

### Minor 1 — inaccurate clean-diff statement

- Verification: valid at the reviewed base. The Plan 2 invariant note and benchmark
  note each had an added blank line at EOF.
- Repair: the Plan 2 note warning is removed in the scoped commit. The already-dirty
  benchmark note had independently lost its trailing blank before this repair wave;
  it was deliberately not staged or rewritten. Final whole-worktree
  `git diff --check` produced no output.
- Files: one now-removed survival-invariants working note; an unrelated dirty
  power-profile benchmark note was preserved at the time. Git retains both.
- Coverage: final `git diff --check`.

## Binding interpretations

- The design prose says lifecycle startup includes the resource guard, while the
  binding whole-branch review and current operations contract say it must remain
  disabled until its later escalation is accepted. The catalogue therefore records
  `agent-resource-guard.service` as optional and intentionally inactive; lifecycle
  verification proves it stays down.
- The stable installer wrapper links may exist before first publication because
  they are unresolvable without `current`. `current` is the sole authoritative
  value and the only operational cutover.
- A missing/unknown kernel boot identity cannot justify comparison of persisted
  monotonic epochs, so it deliberately selects immediate degraded-response egress.
- `RESTART`'s checkpoint request is a shared durable request followed by bounded
  grace. Work which does not reach a sound record boundary is explicitly interrupted
  and retains an OpenCode session when one can be recovered; no success is invented.

## Architectural manifesto audit

- **Fractional distillation:** Telegram input is reduced successively to update ID,
  exact accepted projection, disposition/command enum, lifecycle state/effects,
  atomic attempt result, completion/critical intent, and delivery fact. Unit
  catalogue categories, runtime snapshots, accepted timing policy, and data-health
  incidents each represent one concern once.
- **Vertical layerwise agnosticism:** the lifecycle reducer knows effects, not
  systemd/HTTP/filesystem mechanics. The production constructor interprets every
  effect and tests replace only literal systemd, process, clock, HTTP, or filesystem
  fingertips. There is no second successful fake semantic route.
- **Contract-led modularity:** exact JSON field sets, enums, IDs, unit/action
  allowlists, adapter keysets, catalogue presence, modes, ownership, deadlines, and
  postconditions fail explicitly. Zero exit alone is never recovery.
- **Semi-permeable horizontal boundaries:** exact peer UID crosses the privileged
  socket; directory ownership encodes one-way inbox and critical-message flow;
  root message content and gateway delivery state are distinct records; survival
  units never enter the destructible catalogue.
- **Cycles and recovery:** gateway child observations close through the main-PID
  watchdog and systemd restart. Lifecycle command effects close through direct
  critical intents and gateway egress. Durable startup/idle scans close every crash
  cut; quarantine is a reported data cycle rather than a process restart loop.
- **Policy ownership:** command vocabulary, authorized UID, units, action forms, and
  source/delivery authority are fixed laws. Durations, stage membership, prior
  activity, and pause state are validated varying policy with one owner each.
- **Transactional construction:** atomic fsync/rename records, immutable effect
  attempts, last-known-good timing publication, content-addressed releases, and the
  `current` cutover expose only complete values. `sending` and `delivery_unknown`
  preserve ambiguity rather than lying after a crash.
- **Three-month change surface:** a service change is localized to the installed
  semantic catalogue; a timing key to the central schema/config; an update shape to
  ingress disposition; and a literal effect to its narrow adapter. No class, hidden
  mutable object state, inheritance, or CamelCase identifier was introduced.

## Verification evidence

Final commands and exact outcomes:

```text
python3 -m unittest -q tests.test_survival_records tests.test_survival_protocol tests.test_survival_lifecycle tests.test_survival_gateway tests.test_survival_guardian tests.test_system_control tests.test_time_policy tests.integration.test_survival_processes
Ran 170 tests in 30.516s — OK

python3 -m unittest discover -s tests -v
Ran 264 tests in 8.347s — OK

python3 -m py_compile survival/*.py ecosystem/time_policy.py
exit 0, no output

bash -n scripts/install-survival-plane scripts/cointelprofessional-gateway scripts/cointelprofessional-guardian
exit 0, no output

systemd-analyze verify services/system/cointelprofessional-survival.slice services/system/cointelprofessional-gateway.service services/system/cointelprofessional-guardian.socket services/system/cointelprofessional-guardian.service
exit 0, no output

git diff --check
exit 0, no output

sudo -n true
exit 1; confirms no noninteractive root authority for an installed two-UID test

unshare -Ur true
exit 1: unshare: write failed /proc/self/uid_map: Operation not permitted
```

Focused red/green repair runs first reproduced failures for acknowledgement
durability/bounds, inactive-unit cgroup proof, checkpoint readability, parent timing
reload, guardian `ProtectHome`, multi-incident reporting, and prior inference-state
restoration; the corresponding focused modules then passed before the final suites.

## Scoped commit and worktree preservation

- `1a27928534b0311341f907a192022214106f7349` — complete production lifecycle,
  gateway resilience, timing ownership, permission layout, transactional installer,
  documentation, and focused evidence.
- This report is committed separately so it can cite the implementation commit.
- Only the 23 Plan 2 implementation/test/documentation paths were staged for the
  implementation commit. Pre-existing unrelated modified and untracked files in the
  shared checkout were left unstaged and unaltered by this commit.

## Concerns and remaining gates

1. Real prohibited-write/allowed-read operations under the installed gateway and
   David UIDs require root-created identities or an enabled user namespace. Neither
   is available in this environment. The contract is structurally and behaviorally
   covered short of that final kernel credential transition.
2. Live systemd, Lemonade, credential, and Telegram acceptance is intentionally not
   evidence in this report because the task expressly prohibited service mutation
   and Telegram contact. Plan 5 must run the documented PID/cgroup/journal/Telegram
   gate before deployment is called live-ready.
