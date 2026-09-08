# Concurrent Qwen commissioning — Astra, 2026-09-07

Integrated shared routing 32fd0ad, cfg admission 50250dd and mixed-cap fix
3dd730b after review. Fresh combined verification: model admission46, resident3,
shared routing7 passed; cfg admission and inference_capacity then failed broadly.
Systematic root cause reproduced: their synthetic route() fixtures omit the newly
authoritative context_mode. models.validate_route freshly produces fixed and,
as required, compares context_mode, returning route_changed:context_mode before
R3 persists a lease. Production models.route returns explicit context_mode.
This is a cross-packet test-fixture migration gap, not permission to remove mode
identity checking. A bounded integration worker must update all still-valid fixed
fixtures/expectations and rerun the combined set; shared realization remains the
next production seam. Do not claim integrated green until that evidence exists.

Admission candidate 791d05b finished returncode0 but awaits conservative absence
reconciliation while Routing remains active. Astra independently passed its 24
existing +9 new focused tests and diff check. DO NOT INTEGRATE YET: review found
_model_slot_limit's caller counts same-model leases only within the current
front/work class. If a single backend model serves both classes, combined active
leases can exceed observed parallel_sequences. Required local correction/review:
count all active leases for the same model against observed physical slots, then
separately enforce class policy (front cap or model work cap). Add literal mixed
front+work test; preserve current distinct-model operation. Also note logical
global indices reserve 0 for front and 1..8 for work, while llama slot ids are
0..7; do not pass logical backend_sequence as id_slot until a backend-qualified
physical mapping is represented. This is a future precise-slot boundary, not a
reason to discard canonical cfg work.

Polling cadence superseded: David now explicitly requests worker checks about
every FIFTEEN minutes, not five. Use an interruptible timer between checks;
do not inspect worker logs/status repeatedly while waiting. User messages or
actual completion notifications can interrupt the wait. Keep hosted usage low.

David is explicitly AFK/asleep, but subsequently approved overnight reused monitor
windows with at most eight live monitors. Use COINTOS_VIEW_MODE=driver within that
bound; reuse idle slots and use afk if a ninth window would otherwise be needed.
This supersedes his earlier blanket AFK window suppression. He asks
for continued economical local MVP bring-up, maximizing usable concurrency while
respecting resource and decision boundaries. Old goal is still blocked; Astra
requested /goal resume; David subsequently resumed the overnight goal. Automatic
continuation is now active. No approval blocker remains for bounded MVP work.

R4-PRECISE next evidence lead (Astra; source inspection, NOT live proof): installed
llama.cpp commit 010be9683 tools/server/server-context.cpp explicitly selects
task.id_slot in get_available_slot (~1542), parses id_slot from request (~4296),
and uses oaicompat_chat_params_parse for both chat completions and apply-template
(~4907/~5037). Slot lookup wraps out-of-range indices (~1511), so the proxy must
validate exact bounds and never use global front-offset lease indices directly.
Investigate parser pass-through and Lemonade forwarding before relying on pinning.
This could establish exact backend incarnation/slot/claim ownership for independent
release. Stream completion still precedes slot.release; EOF alone is not proof.
Source: https://github.com/ggml-org/llama.cpp/blob/010be9683/tools/server/server-context.cpp
The same template parser is a lead for exact request prompt accounting, including
tool formatting, followed by /tokenize. Neither API lead is an implemented pool
reservation or permission to send unadmitted inference.

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

## Timesharing architecture clarification, 2026-09-08

Prefill observation (Sol, 2026-09-08): with Qwen weights resident, a roughly
five-second sample showed GPU busy at 98–100%, three decoding requests advancing
5–8 tokens each, and a fourth processing about 1,000 prompt tokens within a roughly
22K-token prompt. The 4B backend was idle and swap unused. David subsequently
observed all four workers reasoning at a reasonable pace after prefill finished.
This supports prefill interference as a scheduling concern, but is not a controlled
benchmark or a proven request-to-session mapping. Full context replay may incur
this cost on every resume unless reusable KV/prefix state is actually retained.
Decision 0016, the spec and resource plan now require restoration and peer-slowdown
measurements when tuning quanta. No runtime policy or timesharing code changed.

David clarified that logical worker/execution leases should be able to outnumber
physical inference slots. On a configurable/tunable cadence, ideally quick and
initially on the order of minutes, an eligible physical occupant should reach a
safe boundary, persist reconstructible state to disk, release/clear the slot, and
let a waiting lease enter with clean context or saved resume context. Prefer full
usable-context replay when it fits; fall back to destination-sized handoff when it
does not. KV-cache preservation may become a qualified optimization, but is not
assumed and cannot be the only durable state. If measured swapping overhead makes
short slices impractical, lengthen them; an unattended workstation must still give
all eligible leases useful eventual progress. Logical identity, agent generation
and cumulative budget survive turnover; a waiting logical lease owns no physical
R3 sequence. This entry and the canonical decision/spec/plans are documentation
only. Do not infer runtime implementation or disturb the eight live Qwen runs.

Catastrophic-death clarification, 2026-09-08: a dead runner must not strand opaque
lease ownership. Matching process-generation death should revoke runner authority
and trigger cleanup; reuse the physical sequence only after independent evidence
that the bound backend request ended. Always leave an append-only revival artifact
with logical identity, last durable state, cumulative budget, mailbox/artifact
references, crash/release evidence and uncertainty. At minimum a Steward must find
and triage it; eventually a bounded revival protocol should reacquire resources and
resume the same logical work. Never infer completion from death. Documentation only.

Timeout correction, 2026-09-08: the failed `local-r4-slot-wiring-review3` request
ended after roughly 609 seconds with OpenCode's `CURL error: Timeout was reached`
and zero tokens. OpenCode 1.18.29 exposes provider `timeout`, `headerTimeout` and
`chunkTimeout`, each accepting `false`. CointOS-generated anonymous configs now
disable all three. The proxy retains a bounded 10-second backend connect but removes
the post-connect total/read deadline so normal queue residence cannot kill admitted
work. Do not restart the live proxy or existing workers solely to activate this;
activate at the next independently safe drain/restart boundary. Focused R4 tests:
41/41 pass. A broader 123-test selection exposed five existing executor-fixture
errors about obsolete `front_sequences` policy ownership; they are not attributed
to this timeout change and remain separate reconciliation work.
