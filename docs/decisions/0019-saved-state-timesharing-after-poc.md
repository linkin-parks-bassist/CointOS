# 0019: Saved inference state is the canonical post-MVP timesharing model

Status: accepted by David, 2026-09-08. Recorded by Aster (Astra, Codex `/root`;
initially misidentified as Sol, attribution corrected).
Documentation and prioritization only; no runtime activation or implementation.
This supersedes the text-replay-first timesharing direction and mandatory MVP
quantum-turnover gates in decision 0016 and its dependent plans/specification.

Clarified directly by David on 2026-09-09; recorded by Codex agent `/root`.
This preserves his intended operating-system analogy after repeated assistant
answers narrowed it to backend slots. The clarification remains documentation
for later work; it does not change the POC-first delivery order.

## The operating-system contract

David's analogy is a preemptively scheduled operating system: agents correspond
to processes, and the GPU supplies execution time. The scheduler runs on the CPU
while the GPU computes. It chooses which runnable agent receives the next quantum,
according to priority and accumulated service, and arranges the next agent's state
in advance where possible. The desired observable behavior is many persistent
agents making interleaved progress with their complete context preserved.

"50 agents" illustrates oversubscription, not a required population, simultaneous
residency target, or fixed limit. Agent existence does not reserve an equal fraction
of GPU memory or require all agents' caches in RAM at once. Each admitted agent
retains its declared context capacity within its model's supported limits. Aggregate
pressure changes residency, waiting and service rate; it must not silently divide
that capacity by the number of agents. Disk holds suspended state, RAM holds the
working set and bounded staging, and GPU execution uses the currently selected
state. Total stored state and metadata still consume resources. No numeric RAM
estimate for the illustrative population was established in this conversation.

Preemption must be imposed by the runtime while generation is underway. Waiting
for every complete response or for the model to volunteer a yield is insufficient.
A candidate implementation uses bounded decode/prefill chunks as safe scheduling
points: quantum expiry prevents further submission for that agent, pending work
reaches a consistent boundary, then another agent runs. It need not interrupt an
arbitrary instruction inside a GPU kernel to supply preemptive agent scheduling.
The backend must expose and measure the longest non-preemptible interval, including
long prompt processing. A cancellation that discards computed state does not
satisfy the pause contract.

Priority governs GPU service. Request count, generated-token count and wall time
including disk waits are not interchangeable with accelerator time. Account for
actual execution and switching costs; batched execution needs an explicit shared
cost rule. Scheduling should preserve progress for lower-priority runnable agents
under a feasible workload, while favoring urgent work. Exact fairness policy,
quanta and latency guarantees remain to be selected from measurements. Grouping
compatible work for efficiency must not turn model residency into permanent
priority over other agents. Agents awaiting tools or disk I/O need no GPU quantum.

## What "swap the pointer" means

The intended abstraction is selecting an agent's complete execution state by a
stable handle. When compatible state and weights are already addressable, a
backend may implement much of this through references, bindings or block mappings
after synchronization. A raw pointer alone cannot make nonresident bytes available.
The pager must first restore missing state; that cost belongs below the scheduling
contract and must remain measurable. David explicitly accepts loading and aiming
costs. They justify staging and longer quanta, not abandoning time sharing.

An agent does not require a private copy of immutable weights. Agents using the
same model may share them while retaining separate mutable continuation state.
Changing models selects the appropriate weights and that agent's matching state;
it never reinterprets one model's KV tensors as another model's tensors. Residency
and paging mechanisms may differ by backend or hardware without changing what an
agent's context means.

The preserved state must be sufficient to continue at the chosen boundary: token
history and positions, KV and any recurrent memory/checkpoints, sampler RNG and
history, grammar/stop state, pending tokens or logits when needed, and references
to any additional required model inputs. Task identity, authority, cumulative
budgets, tool results and already-published output remain consistent with it.
Snapshot compatibility includes model/adapter identity and relevant backend layout
and version. A KV-only export is not automatically a complete execution snapshot.
Restore must not duplicate a tool side effect or emit an already-delivered token.

Keep these concerns as plain records and functions: agent continuity owns logical
identity; CPU scheduling owns service policy; memory management owns placement and
snapshot lifetime; backend adapters own device execution, synchronization and state
encoding. They share explicit identities and inspectable accounting. Backend slot
numbers and cache layouts must not become definitions of agent identity or context
capacity. Actual queues are justified at CPU/GPU and I/O boundaries; this does not
authorize class-based software or opaque autonomous actors.

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

Begin with a small proof, for example three logical agents sharing one physical
execution allocation with unequal priorities. Interrupt long generation repeatedly,
save and evict one state to disk, run another, then restore the original. Compare
continuation with an uninterrupted reference under controlled sampling/backend
conditions, and demonstrate that full-history prefill was avoided. Do not assume
bitwise output equivalence across different nondeterministic execution paths.
Show that priorities affect measured service, every eligible test agent progresses,
and increasing logical population leaves each agent's context limit unchanged.
Measure peak memory including transient copies, transfer time, GPU idle time,
preemption latency and useful work. Repeat with different models and the actual
Qwen state format only after the basic boundary is sound. These are proposed
post-MVP acceptance experiments, not tests executed by this documentation update.

Expected drawbacks are transfer bandwidth, disk space/writes, synchronization,
serialization, weight-loading cost, memory-bandwidth contention and thrashing when
quanta are too short. More agents divide useful service and can increase response
latency. A long-context inference still needs a supported execution working set;
virtualizing agent lifetimes does not remove model limits. Whole-state paging is
enough for the initial hypothesis; fine-grained demand paging is a separate design
choice. The value David seeks is persistent independent agents with scheduled
progress, accepting these costs.

## Evidence of feasibility, not installed-backend acceptance

Primary sources checked by Codex `/root` on 2026-09-09:

- [Salus, Yu and Chowdhury (2019)](https://arxiv.org/abs/1902.04610)
  implements GPU job switching and memory sharing through iteration scheduling,
  including fairness and priority policies. It supports the general scheduling
  idea; it does not establish support on this machine or for complete LLM agents.
- [llama.cpp state API](https://github.com/ggml-org/llama.cpp/blob/master/include/llama.h)
  exposes sequence state export/import and file save/load functions. These are
  useful primitives, not proof of complete resumable generation or bounded
  preemption in the installed Lemonade/Qwen combination.
- [vLLM Ascend recompute CPU offload](https://docs.vllm.ai/projects/ascend/en/main/user_guide/feature_guide/recompute_cpu_offload.html)
  documents preserving preempted KV blocks in CPU memory and restoring them before
  resuming decode. This is a platform-specific precedent, not a Halo implementation
  recommendation, disk-paging proof or adoption decision.

The architecture is credible. Qualifying or implementing the backend mechanisms
remains engineering work. Future coordinators must evaluate backends against this
contract instead of treating the current server's resident slot scheme as the
limit of what CointOS is allowed to mean. Unified KV and continuous batching may
help implement it, but neither alone supplies the requested scheduler and pager.

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
