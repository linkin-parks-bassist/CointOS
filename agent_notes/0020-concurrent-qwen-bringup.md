# Concurrent Qwen commissioning — Astra, 2026-09-07

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
