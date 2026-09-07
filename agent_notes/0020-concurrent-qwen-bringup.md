# Concurrent Qwen commissioning — Astra, 2026-09-07

Current dispatch checkpoint: prior shared-policy/layout packets are finished.
Astra independently passed 10 policy +12 layout tests; layout's -no-kvu typo
was caught, demonstrated red and corrected green. Integrated through c7a325b.
Policy worker's conservative close reconciled absent after both workers ended.
Two implementation-only wiring packets now run in separate observable worktrees:
local-shared-model-routing / Sieve-Routing owns models.py and three scoped tests;
local-cfg-admission-wiring / Sieve-Admission owns inference_capacity.py, resource
JSON and two scoped tests. Exact packets/views are in the ignored SDD ledger.
Their base model/capacity suites passed 46 and 24 tests respectively. Do not
cherry-pick admission packet while prior leases still need its old disk-policy
loader: finish/reconcile both first. Routing adds shared metadata; admission
migrates global counts and bounds work against observed backend slots. Shared
request-pool admission remains explicitly blocked pending its own integration;
these packets alone are NOT eight-worker activation. No broad suite was run.

Latest checkpoint (supersedes running-job statements below): Sieve-Review finished
without scoped findings; Sieve-Policy's fixed-policy reader was independently
checked (six focused tests) and integrated at 4feb403. Both old leases are released;
the first finisher needed conservative absence reconciliation after its peer ended.

David approved eight request slots over one bounded shared context pool. A real
metadata-only load with ctx_size=262144, --parallel 8, --kv-unified and
--kv-unified-per-slot 262144 succeeded: all eight slots reported n_ctx=262144.
Host available memory was 71.2 GiB, GTT used 46.8 GiB, swap/OOM unchanged at zero.
Evidence: ignored ledger shared-eight-profile-probe.json. This proves allocation
and metadata, NOT eight-way generation or aggregate request admission. Restored
the two-slot 131072-per-request build profile afterward; 4B stayed loaded.

Now running, implementation only, separate worktrees and reused monitor windows:
- Sieve-Policy2 / local-shared-pool-policy: inference.cfg and its reader/tests;
  distinguish shared aggregate capacity from per-request maximum (three files).
- Sieve-Layout / local-shared-context-layout: pure observed-context normalizer
  and focused tests (two files).
Packets and exact session/view records use those names in the ignored SDD ledger.
Neither packet migrates callers. Shared-pool aggregate admission, canonical config
activation and precise independent physical release remain required integration
work before eight-slot worker dispatch. Do not admit eight full-size reservations
merely because the backend exposes eight request slots.

Original thesis reconciled in spec/owning plans at 5f98116. David explicitly asks
for actual concurrent local agents, global `.cfg` slots, memory-contended model
time-sharing, spontaneous role work and remote contact; do not narrow MVP back to
a serial maintenance bot. Prefer Qwen normally, keep 4B contingency. 262144 native
context is supported metadata, not yet verified per-agent in the active profile.

LIVE: Qwen reloaded through Lemonade with total ctx_size=262144, --parallel 2,
unchanged batch/ubatch/poll/priority/MTP options; 4B remains loaded. /slots reports
two 131072 slots. Before load all inference leases were released and models idle.
After load: 75 GiB host available, 43.014 GiB GTT used, swap/PSI/OOM zero. GTT grew
about 9 GiB versus the prior single-slot profile; this is a combined allocation
delta, not a measured standalone 262K KV-cache size. Before evidence is retained
in ignored ledger qwen-two-slots-before.json. No kernel/service changes.

93be79e fixes two resident-memory double charges: known explicit fixed-partition
llama.cpp context is already included in observed usage, and resident model weights
need not fit spare model-load headroom a second time. Total KV estimate remains
diagnostic; incremental KV is distinct, rederived from fresh model metadata during
admission. Shared/dynamic modes do not receive this fixed-pool credit. Preserves
fresh pressure/reserve checks. Config now permits two work sequences plus protected
front (total_sequences=3). Astra passed 3 new +46 model +24 capacity +33 enforcement
checks. Local independent review is running; not final acceptance of all resource
accounting or arbitrary backend modes.

Commissioning helper no longer rejects every busy model; R3 owns sequence admission.
Two worker runs launched and BOTH physical Qwen slots observed is_processing=true:

- local-two-slot-accounting-review / Sieve-Review: read-only independent review;
  worktree cointos-concurrent-admission, exec session 48966, OpenCode session
  ses_f84be2305ffe9KbIDivzk4Yvq7, URL http://127.0.0.1:4096.
- local-global-inference-policy / Sieve-Policy: three-file isolated config reader,
  no caller migration; worktree cointos-inference-policy, exec session 54427,
  OpenCode session ses_f84be1e2affeHz1IALCppx3U6r, URL http://127.0.0.1:46215.

Packets/logs/view records are in the existing ignored SDD ledger. Both have native
monitor slots. Wait patiently, check about five minutes apart; do not relaunch.
Conservative R4 release may leave the first finisher reconciliation_required until
both are idle. Inspect actual close outcomes, then use existing exact absence
reconciliation if needed; do not falsify independent request release. R4-PRECISE
remains open. No additional workers beyond admitted slots or global autonomous
service activation is implied by this checkpoint.

Next: review these outputs, wire the global policy into existing owners, complete
independent request release and fair excess-agent admission. Root resource JSON is
the temporary active slot source until the cfg caller migration is accepted.
Then scale measured slots/context and model eviction/resumption; don't call the
two-slot checkpoint complete MVP. Contact worker 1fa88d2 still awaits independent
acceptance; its next subtask remains pending, not forgotten or falsely reviewed.
