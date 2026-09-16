---
status: "unverified"
updated_at: "2026-09-16T10:21:55+10:00"
source: "config/models diff; worker final; 48 tests; fresh real snapshot route evidence 2026-09-16"
---

Current #1: automatic priority-aware inference acquisition is partially repaired and still under qualification. Six isolated real subprocess/client/HTTP-proxy tests pass for native/default Telegram acquisition, exact output allowances, stale capacity repair, priority suspension with retry, waiting cancellation and failed-spawn worker release. Two managed user tests pass for automatic launch and retained exact-session resume. No live GPU or installed-service qualification is claimed.

Repaired allocator defects: trusted user priority is now derived from live authoritative operator/worker identities; lower-priority blockers can be suspended for class slots, shared model parallel slots and known byte pressure. Four new regression tests cover priority, cross-class contention, unissued withdrawal and multiple byte victims. Credential-backed occupancy still requires verified backend termination before reuse.

Repaired resume defect: close replay outcomes leaked across runner generations and rejected cleanup after suspension. New generations clear prior close outcomes; same-generation replay remains strict. Managed user resume tests pass after the repair.

Open recovery checks: caller death/restart and interrupted user-run cleanup need qualification. Waiting for an unloaded model and byte-pressure route admission are not yet automatically repaired in every path. Preserve demand and allocation evidence while these remain unresolved. Next check: qualify recovery and scheduling before claiming #1 complete.

Repaired launcher defect: the proxy script could fail to import ecosystem outside the installation root. It now changes to that root and executes the module; absolute --help launch from /tmp passed.

Deployment repaired: current code/assets were installed in ~/.CointOS, four divergent KT spine owners were reviewed and reconciled, and all eleven rendered user service/path/timer definitions were adopted with backups. Loaded command paths and working directories now resolve ~/.CointOS, including the proxy unit. Installed CLI/proxy --help checks pass. Services are now online under David explicit activation request. Installed managed work inference and default fast control inference both succeeded locally; work allocation and worker released cleanly. Saturated priority, actual Telegram exchange and restart recovery remain unqualified.

Intentional shutdown is not a defect. Services were deliberately stopped for substantial changes. Previous Telegram record-ID and obsolete fixture defects were repaired; misplaced verifier tests were removed. The final full suite passed all 781 tests in 49.549 seconds after these source repairs; startup/basic installed inference checks pass; full restoration qualification remains outstanding.

Startup compatibility defects repaired: status excludes historical .opencode.json sidecars and scheduler defaults missing/null legacy authority to ordinary. Focused scheduler/intake/native tests passed after these fixes. Legacy queued jobs lacking verified routing requirements remain deferred, preserving records; next check is requirements recovery before dispatch, not silent privilege elevation.


Current allocation work: native/user cleanup and request-time dead-owner ghost reconciliation are source-complete and pass795 full/105 focused existing checks. Watchdog wiring and runtime paths repaired. Both workers closed, sessions retained and resources released. Installation/live saturation/restart qualification pending. Remaining policy gaps: live-owner idle reservations, uncorrelated stale claims, unloaded-model acquisition and route byte-pressure handling. Availability must propagate automatically; no manual lease cleanup.

Remaining #1 availability gaps: live agent tool/wait phases still hold physical reservations; stale histories without correlation/completion proof and unloaded-model/byte-pressure integration remain unfinished. `reacquire_sequence` is source-only and unwired, so credential renewal/rebinding does not yet park and reacquire live sessions. Installed dead-owner ghost reclaim and rapid-response closure demonstrated with other inference running. Core services online. Next integrate park/reacquire while preserving credential identity, context and session; avoid arbitrary timeout or aggressive polling.

Dispatch-barrier audit 2026-09-15: exact OpenCode version allowlisting was an arbitrary terminal gate. A patch update from 1.18.30 to 1.18.31 stranded an ordinary managed worker at capacity preflight despite a loaded compatible backend. Source and installed runtime now treat version as observed metadata; unknown versions add no client-specific ceiling and remain bounded by fresh backend capacity plus configured output reserve. The temporary copied catalogue entry was removed. Existing10 client and24 capacity checks pass after updating stale policy expectations; no new test case was authored.

Foreseeable remaining barrier family: requested unloaded models have no automatic load producer; missing model metadata/capability facts can cause indefinite retry without a repair producer; dead managed-operator controllers can leave `runner_starting` records with no evidence-bound automatic resumption; and whole-session physical leases block available capacity. Capacity-preflight exceptions and ordinary contention already return operator work to `ready` and retry, so they are waits rather than terminal denials. Next checks: finish credential-preserving park/reacquire, add evidence-bound operator-controller recovery, and connect unloaded-model/metadata refresh to wake queued requests. Authorization, explicit panic/drain, observed incompatibility, and irreducible physical shortage remain legitimate refusal boundaries.

Repaired: live agent tool boundaries now release verified physical capacity and automatically reacquire through priority scheduling while retaining the bearer, worker and OpenCode session. Actual generation311->314 evidence demonstrates park/rebind around a tool call; final cleanup is clean. Remaining newly observed barrier: operator routing estimated4096 prompt tokens and admitted Qwen3.5's16384 context, but the actual fresh OpenCode request was19310 tokens after injected instructions. OpenCode emitted `exceed_context_size_error` in JSON and exited0; operator cleanup mislabeled it run_finished. Next check: capture the effective client envelope before routing or learn it from this semantic error, retain the session/task, and retry on a fitting model rather than terminally succeeding.

Repaired: a resource-free managed-operator request no longer remains abandoned when its controller dies. The watchdog restarts only a precisely identified dead controller before executor/worker/inference acquisition, using a durable launch gate to prevent duplicate or clobbered ownership. Installed live recovery produced RECOVERY_OK and clean release/revocation/quiescence. Later-phase deaths still use evidence-bound cleanup. Remaining dispatch barriers are unloaded-model/metadata repair and queued wakeup, route byte-pressure integration, and broader saturated priority/restart qualification.

## Scarcity-shaped restriction audit (active, 2026-09-15)

This audit now covers silent throttles as well as terminal allocation barriers. A
number is not defective merely because it is fixed: protocol widths, permissions,
HTTP status codes, and bounded diagnostic reads remain outside this list. A
resource, inference, agent-lifetime, or recovery restriction needs measured
machine/workload evidence and non-loss behavior.

Confirmed defects or unresolved high-priority risks:

- **General worker output starvation / SADS:** the former 4096-token output cap
  terminated a live Qwen turn at exactly 4096 tokens. Source and installed policy
  now request 32000, observable launch verifies the effective 131072/32000
  context/output pair, and terminal `length` causes exact-session continuation.
  Repeated length remains an emergency rather than success. Owner:
  `why/did/cointos/limit/agent/output/to/4096/tokens.md`.
- **Measured llama.cpp batch setting, broader scope pending:** dynamic, boot, and
  resource-control load paths force `--batch-size 512 --ubatch-size 128`. A
  controlled Qwen3.8 A/B/A run measured 186–188 uncached prompt tokens/s with
  512/128 versus 131.7 with upstream defaults 2048/512, with decode essentially
  unchanged. Retain 512/128 for the current qualified Qwen3.8 backend. It remains
  unqualified as a universal setting for other models/backend versions. Owner:
  `why/does/cointos/force/llama/cpp/batch/size/512/and/ubatch/size/128.md`.
- **Terminal agent budgets:** executor budgets can signal a running agent when
  task/run time, output bytes, evidence, attempts, or child ceilings are reached,
  then record `checkpoint_required` plus `logical_run_state: terminal`. The
  OpenCode session may be retained, but automatic semantic handoff is explicitly
  deferred. Current constructors include 300-second runs, 900-second tasks, two
  attempts and 65536 output bytes. Owner:
  `why/can/cointos/task/budgets/stop/incomplete/agents.md`.
- **Repaired stale Qwen reasoning cap:** the unexplained saved
  `--reasoning-budget 2048` was removed with a non-merging controlled reload.
  Fresh saved recipe options and the live Qwen3.8 command both omit it. Recheck
  after future option updates/reloads. Owner:
  `why/does/qwen3/8/have/a/2048/reasoning/budget.md`.
- **Repaired unloaded-model metadata barrier:** valid registry size, capabilities,
  context and recipe now flow into unloaded records; parameter count and synthetic
  context quantum no longer gate physical fit; parallelism comes from explicit
  dynamic load policy (currently one) when no live observation exists. A fresh
  real snapshot produced an admitted unloaded route. The next blocker is route-level
  GTT/host pressure being evaluated before reclaimable idle residency. Owner:
  `how/does/cointos/load/resident/inference/models.md`.

Restrictions requiring evidence review before retention or removal:

- dynamic-model `parallel_requests: 8`, introduced by a commit titled “admit eight
  parallel Qwen requests” without a measured per-model/context qualification;
- 32 GiB protected-host, 8 GiB Coin, 12 GiB load-transient, and 64 GiB
  unknown-model reserves, including duplicated legacy/current policy forms;
- `maximum_work_models: 1` and the relationship between two Lemonade LLM residency
  slots, the pinned control model, and reclaimable work residencies;
- fixed control-agent tool rounds/deep attempts, watchdog output/evidence limits,
  proxy body/header limits where they can truncate legitimate agent state, and
  repaired executor cleanup defaults now use the shared 10-second policy deadline;
- model/context/output settings persisted in Lemonade recipe options but absent
  from current CointOS policy, because stale saved options can reappear on reload.

The audit disposition for each item is: demonstrate a protocol or measured
workload/physical reason and durable recovery behavior; otherwise remove the
override, derive it from fresh backend/machine facts, or replace terminal failure
with retained priority-queued continuation. Current governing policy is
`what/is/the/local/strix/halo/resource/policy.md`.

Current handoff: the registry snapshot wiring worker completed production code and all checks, then entered OpenCode compaction while drafting its KT rewrite. The coordinator stopped it, recovered and applied the prepared leaf, and verified no worker unit remains active. This was not SADS: the exact session is retained and the completed work was recovered. The remaining defect is the routing requirement for facts absent from the unloaded registry, not the normalizer wiring.

- **Unsupervised verification-process leak:** two duplicate operator-inference test processes survived abandoned coordinator tool calls for about 94 minutes, sleeping in an unbounded retry loop with no children or output consumer. They were terminated and a later full suite had already passed, so no current code failure is established. Future recurrence must preserve the exact wait reason/trace before cleanup; verification launchers should supervise and reap interrupted commands. Owner: `why/did/operator/inference/tests/remain/running.md`.

Overnight progress 2026-09-16: optional `parameter_count` is source-complete and coordinator-qualified. The observable worker exited 0 with a final stop; direct semantic checks and all 50 existing model-admission tests pass. No worker process remains. Parameter count no longer controls metadata verification or route admission, and `choose_route` uses positive `model_bytes` as a deterministic fallback ranking fact. Next owner: `why/does/cointos/require/supported/context/quantum.md`.

Overnight progress 2026-09-16: the unsupported context-quantum barrier is source-complete and coordinator-qualified. Two tiny observable Qwen workers removed the gates and arithmetic; both exited 0. Two obsolete tests enforcing invented rounding/denial were deleted by a third observable worker; the remaining 48 model-admission tests and a direct exact-context missing-quantum route/revalidation check pass. The earlier combined worker's 45-minute no-edit attempt is recorded in the owner as task-sizing evidence.

Overnight progress 2026-09-16: unloaded parallel-source wiring is complete. The observable worker exited 0; 48 model-admission tests and fresh real inventory routing pass. DeepSeek-Qwen3-8B now clears metadata/context but is deferred by `gtt_capacity` while an idle work residency is reclaimable, so byte-pressure/reclamation ordering is the active allocation barrier. A separate admitted `gpt-oss-120b-mxfp-GGUF` record reports only 1,589,137,900 bytes; verify registry/artifact provenance before using that admission as live-load evidence.

Overnight progress 2026-09-16: route-level host/GTT pressure no longer prevents an unloaded request from reaching realization. The route carries `realization_pressure`; loaded-model pressure remains an exclusion; the existing verified reclaim/load producer owns unload, backend attempt, postcondition and wait behavior. The observable worker exited 0, 47 remaining model tests and a direct branch check pass, and the obsolete pre-reclamation denial test was removed without replacement. Next check is installed live qualification with a trustworthy unloaded model artifact. The `gpt-oss-120b-mxfp-GGUF` candidate is excluded from that qualification because Lemonade's live API says 1.48 GiB while its installed registry says 63.4 GiB; owner: `why/does/the/gpt/oss/120b/mxfp/registry/size/report/1/48/gib.md`.

Installed qualification 2026-09-16 closes the route-pressure/reclamation barrier for an exact unloaded model: DeepSeek-Qwen3-8B was admitted with observed GTT pressure carried as realization evidence, idle Qwen3.8 was reclaimed, DeepSeek loaded and verified live, and Qwen3.8 was then restored pinned with 131072 context and MTP while the Qwen3.5 control model remained live. Remaining #1 work is priority-aware suspension beyond idle victims, restart/saturation breadth, and agent budget/recovery barriers; the anomalous gpt-oss size remains separately unresolved and excluded from use.

Overnight progress 2026-09-16: ordinary executor budget exhaustion with an exact retained OpenCode session now queues the same job as `ready`/`continuing`, resets consumed slice accounting, and uses the existing exact-session resume path; only missing-session exhaustion remains a terminal emergency checkpoint. The observable worker exited 0 and 42 existing executor tests pass. This is source-only until installed real exhaustion/resume qualification. Fixed constructor numbers remain under audit because needless slicing still wastes work even when it no longer causes SADS.

Overnight progress 2026-09-16: task budgets can now express no ceiling with JSON `null`/Python `None` for any required dimension; usage remains validated and finite ceilings behave unchanged. Nineteen existing contract/budget checks and a direct unlimited-budget check pass. The arbitrary constructor values are still active until their next mechanical conversion; child ceilings may remain as authority bounds rather than agent-lifetime restrictions.

Overnight progress 2026-09-16: verification, scheduled-review, and sole-survivor task constructors now have no run, task, attempt, output, or evidence ceilings. Child limits remain as explicit authority bounds. Sixty-six existing contract/resource-control checks pass. Together with exact-session continuation for any retained finite budget, this removes the known ordinary agent-lifetime SADS path in source; installation and a real forced-slice resume remain to qualify it.

Overnight progress 2026-09-16: Cointelprofessional deep control no longer dies after six tool rounds. The loop remains active until a valid terminal tool, cancellation, authorization boundary, panic, or resource wait resolves it. Twenty-seven existing checks and a direct eight-round completion pass. The fixed 1400 output-token and 180-second request arguments remain separate scarcity/recovery questions.

Failed-but-recovered probe 2026-09-16: replacing deep control's 1400 output cap with the canonical 32000 allowance caused exact-model Qwen3.5 managed acquisition to wait indefinitely rather than route to available larger capacity. The slice was reverted and 27 focused checks pass. The actual defect is now scoped: control acquisition must choose/reroute to a model that fits actual prompt plus output before the cap can be removed. The owned hanging test process was interrupted cleanly; owner: `why/does/cointos/limit/deep/control/output/to/1400/tokens.md`.

Overnight progress 2026-09-16: role prompts no longer tell steward, lead, worker, intake, or chunker agents to stop after arbitrary minutes, attempts, or fallback marker counts. Scope/acceptance completion or a concrete resumable blocker now governs. The five sections were inspected and the removed phrases are absent.

Prompt-level lifetime cleanup is complete: steward, lead, worker, intake, and chunker no longer carry the old numeric stop rules. The remaining `_base.md` reference to task-contract dimensions is descriptive and supports optional/unlimited values; it is not itself a finite ceiling.

Overnight progress 2026-09-16: native managed inference no longer waits forever merely because its exact route is admitted but unloaded. It calls the verified realization producer once, records failure as retained waiting, and refreshes inventory after success before acquiring worker/sequence capacity. Sixteen existing native checks and a direct branch check pass. Installed live exact-model inference qualification remains next.


Executor cleanup timing repaired 2026-09-16: launch-failure cleanup, gated-child cleanup, and recovered-runner stopping now default to `executor.cleanup_deadline_seconds = 10` through the shared time-policy owner. Explicit caller timeouts remain available. The observable Qwen worker exited cleanly; 42 executor and 8 time-policy checks pass.

Observable dispatch provider-case barrier repaired in source 2026-09-16: two lowercase `lemonade/...` launches bypassed capacity injection and died before inference with opaque server errors. `prepare_environment` now case-folds the Lemonade provider, rejects empty local model IDs, and preserves hosted behavior. Ten launch checks pass; installed lowercase live qualification remains.

## Current cleanup evidence (2026-09-16)

The full source suite now passes 791 tests in 62.194 seconds after aligning two stale fixtures with the shared cleanup deadline and exact-session compaction behavior. The remaining Cointelprofessional usability barrier is fitting-model selection for deep control: raising its 1400-token output cap to the canonical 32000 allowance currently makes exact-model Qwen3.5 wait because that model cannot fit the prepared input plus output. The acquisition path must route the request to observed fitting capacity, then installed Telegram/deep-control behavior must be live-qualified. The separate 180-second backend request timeout and broader saturated priority/restart behavior remain open recovery work.
