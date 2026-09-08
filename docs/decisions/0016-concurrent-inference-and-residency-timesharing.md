# 0016: Reconciliation of the original concurrency thesis

Status: original intent reaffirmed by David, 2026-09-07. Not a new product decision.
Astra records the correction to its narrowed MVP translation;
implementation and activation remain outstanding.

Delivery and mechanism amended by David, 2026-09-08: decision 0019 is authoritative.
Computed inference-state snapshot/restore is the canonical scheduled switching
path; its difficulty review and implementation are top post-MVP work with D9.
A slow POC is acceptable. Scheduled quantum-turnover proofs are not MVP gates.

Lease ownership and reuse follow [decision 0018](0018-liveness-owned-leases.md):
current bound-agent liveness is authoritative, while completion, death cause and
revival evidence are separate from the ability to reuse capacity.

## Product contract

CointOS schedules many durable agents over concurrent model-server capacity.
Agent lifetime, an inference request, a physical backend slot, and model residency
are distinct resources. An agent awaiting inference or executing tools need not
monopolize a physical inference slot. Agent count is not the physical slot count.

Run requests concurrently while their selected models have available slots and
memory. Queue and fairly time-share when requests exceed those slots. When a
requested model is absent, load it if it fits; otherwise select eligible resident
models for checkpoint/drain and eviction, service the waiting model, and later
resume displaced work. Preserve priority, aging and bounded quanta so neither
continuous arrivals nor model-local batching starve other work. Never unload a
model underneath an unaccounted active request or lose agent continuation state.

Logical worker/execution leases may therefore outnumber physical backend slots.
An R3 sequence lease represents only the interval in which a logical run actually
occupies a physical slot; a queued or paused logical lease must not retain that
sequence allocation. Under oversubscription, the scheduler periodically selects
an eligible occupant to yield at a configurable, tunable time quantum. Before the
slot is cleared, it reaches a safe request boundary and durably records enough
state on disk to reconstruct the run: conversation/context, task and authority
contract, cumulative budget, tool results, mailbox state, artifacts and evidence
references. Only an attested durable checkpoint permits ordinary slot release.

The next waiting logical lease receives the physical slot with clean context on
its first run, or with its saved continuation reconstructed on a later slice. The
canonical scheduled-resume path restores saved KV and all other required inference
state, staging disk-to-DDR transfers while peers continue GPU work where supported.
Full-context replay or destination-sized handoff supplies recovery when a snapshot
is unavailable or incompatible. Yield and resume preserve `job_id`, logical
lease identity, `agent_generation` and cumulative budgets; they are not new task
attempts. Physical context/KV is cleared or replaced independently of that durable
identity.

The target is fast context turnover, initially on the order of configurable
minutes, so several logical agents make visible progress over an unattended
workstation interval. This is a performance hypothesis to measure, not a claim
about the installed backend. If safe checkpoint/reconstruction overhead makes a
short quantum inefficient or unreliable, increase the quantum rather than weaken
durability, fairness or resource accounting. Saved inference-state restore is the
intended normal mechanism, subject to model/backend-specific qualification; it is
never the sole copy of durable agent/task state. Long I/O staging is acceptable
when other agents remain productive. Measure its GPU stall separately from elapsed
transfer time and shared DDR contention.

Prefill is a material turnover cost even with resident model weights. Replaying
saved text can require rebuilding its KV state, consuming GPU compute and slowing
other slots that are decoding. Quantum tuning must measure context reconstruction,
time to first useful output, useful decode time and peer slowdown separately from
weight loading. Evaluate cold replay and actual cache reuse independently; full
text capture guarantees reconstructibility, not cheap resumption. Choose quanta
that amortize measured restoration cost while preserving bounded waiting. Consider
staggered or backend-supported chunked prefill during later performance experiments.
These are documentation requirements; timesharing implementation remains deferred.

Catastrophic runner death must not strand a lease indefinitely. Detecting the
matching process generation's death ends that runner's authority and initiates
release/recovery automatically. Physical capacity becomes reusable after the
owning observer confirms that the bound backend request has also terminated; PID
death alone must not release a still-running request or somebody else's slot. The
transition writes an append-only, steward-discoverable revival artifact containing
the logical identity, last durable continuation/checkpoint references, cumulative
budget, mailbox/artifact references, death and release evidence, and any uncertainty.
The minimum MVP behavior is a visible recoverable/pending-revival record. The
eventual behavior is a bounded revival protocol which safely reacquires resources
and resumes from that record without treating the crash as successful completion.

Backend slot identity includes model/backend incarnation; slot 0 on two different
backends is not one resource. Releasing one request must not await unrelated slots
becoming idle. Implement the precise-release successor in decision 0012.

Queue residence and paused time are ordinary operation, not request failure. A
CointOS-launched inference client must not impose a fixed total, response-header,
or inter-stream-chunk deadline which can expire merely because admitted work is
waiting for its turn. Keep connection establishment, malformed input and health
probes bounded. Once connected and admitted, explicit cancellation, lease/budget
policy, verified runner death or transport/backend failure owns termination; elapsed
queue time alone does not. This applies to the OpenCode adapter and the proxy's
backend connection independently.

## Policy ownership

Slot counts belong in one global `.cfg` policy, proposed `config/inference.cfg`,
with a default and model-specific overrides. Requested slots, context per request,
aggregate resident context/cache budget, and actual observed backend capacity are
separate fields. One validated policy feeds loading, admission and scheduling;
remove competing constants rather than retaining several authorities. This file
and its initial reader exist at 4feb403 but are not yet consumed by runtime callers.
Reuse the existing configuration mechanisms.

Qwen3.8-27B is David's preferred normal model, including ordinary control work;
4B is retained for contingency availability. Model choice remains changeable.
Replace the one-work-sequence, one-work-model and blanket-any-model-busy rules:
resource contention, not those historical constants, determines serialization.
This supersedes those restrictions and normal-4B preference in decision 0006.
Preserve measured memory boundaries and contingency/desktop availability.

## Context and memory evidence

The installed Qwen backend reports native `n_ctx_train=262144`, currently allocated
131072 per request. Installed Lemonade accepts `--ctx-size`; installed llama.cpp
advertises parallel slots, unified KV, per-slot context limits and RAM prompt cache.
An eight-slot unified-pool allocation probe subsequently reported 262144 for every
slot with 46.8 GiB GTT used and 71.2 GiB host available. David approved this shared
pool direction. This is metadata/allocation evidence, not eight-way inference or
aggregate admission acceptance; the active build profile remains two fixed slots.
Update client limits and admission representation together; do not divide a total
262144 allocation among several slots and call each slot 262144. Shared pools must
account for aggregate use independently of each request's permitted maximum.

David configured 100 GiB GPU capacity and reports successfully loading an 80 GB
model. This boot also exposes `mem_info_gtt_total=68719476736` and TTM pages_limit
16777216 (4096-byte pages); reading amdgpu gttsize was permission-denied. These are
different observations, not proof that David's configured limit is 64 GiB or that
an 80 GB model cannot load. Reconcile their actual allocation semantics before
changing kernel settings or describing one reading as the hardware maximum.

## Implementation order and acceptance

First qualify 262K context and a multi-slot Qwen profile against actual memory;
make slot policy canonical and remove accounting assumptions that reject valid
concurrency. Implement independent request release and slot admission for the POC.
Keep required durable context/model continuation. After MVP, review difficulty and
implement saved-state contention timesharing through the centralized compatibility
boundaries of decision 0017, as specified in decision 0019.

MVP acceptance must demonstrate overlapping Qwen requests, release while a peer
remains busy, and required model-change continuity with contingency availability.
D10 post-MVP acceptance adds more logical leases than slots progressing across
repeated saved-state turnovers. Measure queue time, snapshot/staging/import time,
GPU stall, peer slowdown and useful generation separately, preserving identity
and cumulative budget. The monitor-window demonstration and review of
contact worker commit 1fa88d2 remain pending, not superseded or silently accepted.
Crash acceptance additionally kills a bound runner, observes its request end and
physical release independently, and finds the durable revival artifact through the
ordinary Steward discovery path; absence of an automatic reviver must remain an
explicit pending-revival limitation rather than an invisible orphan.
