# 0016: Reconciliation of the original concurrency thesis

Status: original intent reaffirmed by David, 2026-09-07. Not a new product decision.
Astra records the correction to its narrowed MVP translation;
implementation and activation remain outstanding.

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

Backend slot identity includes model/backend incarnation; slot 0 on two different
backends is not one resource. Releasing one request must not await unrelated slots
becoming idle. Implement the precise-release successor in decision 0012.

## Policy ownership

Slot counts belong in one global `.cfg` policy, proposed `config/inference.cfg`,
with a default and model-specific overrides. Requested slots, context per request,
aggregate resident context/cache budget, and actual observed backend capacity are
separate fields. One validated policy feeds loading, admission and scheduling;
remove competing constants rather than retaining several authorities. This file
is not yet created or consumed. Reuse the existing configuration mechanisms.

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
Thus 262144 is a supported configuration target, not yet a live-accepted allocation.
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
concurrency. Implement independent request release and slot admission, then
contention time-sharing and memory-driven model eviction/resumption. Backend KV
save/restore is an optimization requiring model-specific evidence; durable sessions
and replayable continuation are the correctness boundary, not an invented KV API.

Acceptance must demonstrate overlapping Qwen requests, release while a peer remains
busy, more agents than slots making progress, and a memory-contended model switch
with preserved agent state and contingency availability. These are central MVP
requirements, not post-MVP polish. The monitor-window demonstration and review of
contact worker commit 1fa88d2 remain pending, not superseded or silently accepted.
