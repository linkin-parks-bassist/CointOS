# 0019: Saved inference state is the canonical post-MVP timesharing model

Status: accepted by David, 2026-09-08. Recorded by Aster (Astra, Codex `/root`;
initially misidentified as Sol, attribution corrected).
Documentation and prioritization only; no runtime activation or implementation.
This supersedes the text-replay-first timesharing direction and mandatory MVP
quantum-turnover gates in decision 0016 and its dependent plans/specification.

## Intended mechanism

At a supported pause boundary, capture the worker's computed inference state:
KV cache and any required recurrent state, positions, checkpoints, token history
and sampler/continuation state. Persist a snapshot bound to the logical run and
compatible model/backend configuration, alongside the durable task, conversation,
authority, budget, tool-result and artifact records. Release its physical working
allocation so another logical worker can run. A later slice restores the computed
state rather than normally replaying the entire conversation through the model.
Full text remains recovery evidence and a reconstruction path when a snapshot is
unavailable or incompatible; it is no longer the canonical normal switch mechanism.
Snapshot restoration must demonstrate actual computation reuse and correct
continuation, not merely a successful save/restore API response.

Schedule disk-to-DDR staging while other resident agents continue useful GPU work.
David explicitly accepts long staging latency: elapsed I/O time is not equivalent
to an accelerator stall. Admit the staged state for execution when ready, with a
short final switch where supported. Preserve run identity and cumulative budgets.
Logical leases may outnumber physical slots. Tune quanta and staging lookahead
against useful GPU work, fairness and memory limits rather than requiring every
disk transfer to finish quickly.

The intended gain is replacing repeated large-prompt GPU computation with state
transfer. DDR bandwidth, serialization, memory allocation and synchronization can
still compete with generation, especially on this shared-memory GPU. Whether the
installed API permits useful overlap is a feasibility question, not yet measured
or guaranteed. Do not equate host staging with backend slot import; either may
block in a particular implementation. Preserve bounded RAM/GTT headroom, including
staged snapshots, resident state and transient copies.

## Difficulty review and later acceptance

The first post-MVP review should establish supported pause boundaries; completeness
and compatibility of state for the actual Qwen model (including hybrid/recurrent
state); actual cache reuse after restore; API blocking/synchronization behavior;
RAM/disk/GPU placement and peak allocation; save, staging and import costs; peer
decode slowdown; and cancellation or failed-restore recovery. Determine whether
current llama.cpp primitives suffice or a bounded backend change is needed.

Installed llama.cpp advertises slot save/restore and a RAM prompt cache. That
supports feasibility, not acceptance of this model/backend combination. Retain
model-neutral plain state/capability contracts; backend adapters own literal APIs.
Later acceptance demonstrates repeated N+1-on-N turnover, correct continuation,
bounded memory/waiting, useful peer decoding during staging, and materially avoided
prefill. Report transfer latency separately from GPU stall and useful service.

## Delivery order

David prioritizes proof-of-concept bringup wholesale: a clunky, slow but useful MVP
is acceptable. Concurrent inference, independent reclaimable occupancy, durable
continuation, useful autonomous work and existing contact/survival requirements
remain. Scheduled physical-slot preemption/restore and efficient time-sharing are
post-MVP; their repeated-turnover/performance proofs do not block G2. Ordinary
context rollover and required model-change continuity retain their existing scope.

Immediately after POC acceptance, put these together at the top of the improvement
queue: D10 saved-state timesharing (difficulty review first), and D9 central backend/
runner compatibility boundaries (decision 0017). Initial compatibility need only
cover Lemonade/OpenCode. Small central adapter modules should contain implementation
details so adding support is localized; no additional provider or general plugin
framework is required. Choose bounded implementation packets after the difficulty
review. Other improvements David may recall remain unspecified: preserve a reminder
to revisit them, without inventing additional requirements or MVP gates.
