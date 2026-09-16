---
scope: project local
status: "unverified"
source: "2026-09-15 coordinator inspection of source, worker journal, checks, runtime service state, and central defect audit"
review_when: Recheck after each restoration milestone or priority change.
updated_at: "2026-09-15T23:14:03+10:00"
---

Current #1 priority (David 2026-09-14): fix automatic, priority-aware inference acquisition. Legitimate sole-survivor, Cointelprofessional and user sessions must obtain service by suspending lower-priority blockers and retaining their work for later resume. Complete production wiring and meaningful boundary tests before broader live parallelism restoration.

David's priority order is: restore useful live parallelism with managed allocation; restore live, preemptive Cointelprofessional with remote operating capability; then continue implementing the full spec. Advanced inference-state swapping and a complete role redesign must not become prerequisites for the first useful restoration.

1. Restore managed parallelism.

Audit the actual launch paths, current hardened Lemonade configuration, installed backend capabilities and available memory. Finish the source/runtime-root split wherever execution and durable recovery require it: development source belongs in `~/Projects/CointOS`; an installer deploys required code, configuration, role prompts and assets into `~/.CointOS`, alongside separately protected mutable state/logs. Preserve the hardened configuration as the known working reference while evaluating a bounded concurrency configuration.

Select and qualify the smallest useful concurrency target, initially two local agents. Use shared model weights and measured per-request capacity where supported. Admission must reserve context/KV and output allowances against finite physical capacity, queue excess work, and enforce task budgets and priority. Do not merely increase `--parallel` and silently divide a previously promised context window. If two full intended windows do not fit the measured hardware/backend, record the concrete memory/capacity limit and propose an explicit allocation or backend choice; no hidden smaller-context fallback.

Route every managed launch through fresh capacity derivation, lease-constrained limits and OpenCode resolved-config verification. Keep allocation stable during qualified runs until request-time requalification/recovery is implemented. OpenCode owns normal compaction in retained sessions; custom handoffs remain deferred. Advanced disk KV snapshots are not needed to qualify this first milestone; clearly distinguish ordinary session resume with possible prompt recomputation from exact native state restoration.

Acceptance requires two agents actually making concurrent progress, correctly reported context/input/output limits, excess work waiting without overcommit, cancellation/priority behavior releasing allocation only after verified cleanup, and retained sessions recovering through ordinary OpenCode mechanisms. Exercise representative long-running work including real compaction and conflicting high-priority demand. Preserve evidence of the loaded backend/client configuration and outcomes. Synthetic request-capture tests and serialized queued jobs alone do not establish restored parallelism. Operational adoption follows concrete configuration and focused validation, with a documented return to the known working single-slot setup if qualification fails.

2. Restore Cointelprofessional.

Once managed allocation works, bring the permanent Telegram-facing control plane back through the same admission and priority machinery. Use the existing minimal responsibilities needed for restoration rather than waiting for the complete role shakeup. It must remain responsive while background agents run, acquire service promptly, and safely interrupt/requeue lower-priority work when capacity is occupied. Durable identity, conversational state, incoming commands and execution outcomes must survive restart without duplicate work.

Restore remote capabilities first for truthful health/status, task submission, progress inspection and cancellation/preemption. Extend to the system operations supported by explicit authority boundaries, authenticated Telegram routing and auditable durable outcomes. Remote operation is a control-plane capability, not blanket permission for every action. Recheck the actual service/state owners and credentials without exporting secrets into KT. Qualify the source/runtime-root split before starting affected services.

Acceptance requires an end-to-end Telegram request during background saturation: prompt acknowledgement, correct prioritized dispatch/preemption, durable task tracking and a truthful result/status. Also verify cancellation, restart/recovery, denied unauthorized commands, and limited operating capabilities. A healthy service process alone does not prove restoration. This planning update records the target; it does not itself start services or send messages.

3. Resume implementation of the full spec.

Continue the accepted durable-agent scheduler, messaging and knowledge-tree contracts after the first two live milestones. Redesign the remaining roles around general knowledge-tree machinery and residual task/authority boundaries. Qualify exact-build hybrid-model save/restore and define the complete inference/agent checkpoint before implementing GPU/RAM/disk residency switching. Streaming/scanning live swap remains exploratory. Maintain fair progress for eligible lower-priority work.

Keep internal algorithms, allocation ownership, error paths, invariants, configuration decisions and acceptance evidence in fine-grained KT leaves alongside these broad plans. Fix baseline defects that block a milestone within that milestone; unrelated verifier/test repairs do not displace restoration priorities. Existing capacity source integration is implemented, but live parallelism and control-plane restoration remain unqualified. See `what/is/the/state.md` for evidence and limitations.

The isolated-tested installer is implemented and the application copy is deployed. Operational adoption/root qualification remains necessary before making live services depend on it. Services and agent tool paths must run installed assets without relying on the source checkout. See `what/is/the/intended/cointos/installation/layout.md` and `how/should/standalone/knowledge/trees/integrate/with/cointos.md`. Standalone KT ownership remains separate while its lifecycle/root contract is integrated into CointOS.

Installer progress: `scripts/install-cointos` now stages/copies the explicit payload, preserves operational data and configuration/knowledge edits, records deployment identity and retains rollback material. Six isolated tests pass. Remaining work is operational adoption and broader root/lifecycle qualification; install completion alone does not establish managed parallelism or live Cointelprofessional.

Blanket installation policy: David explicitly authorized automatic all-project access to installed CointOS knowledge, without an interactive installer prerequisite. Six installer tests pass, including real CLI noninteractive repeat installation/approval in an isolated registry and outside-directory `cointos:` lookup; an unrelated registered root remains ask and general bypass remains disabled. The implementation uses KT’s public register/access CLI through a bounded approval terminal, without registry-internal writes.

Allocation restoration refinement: first make acquisition automatic at actual production entry points, including fast/deep Cointelprofessional and trusted user sessions. Verify priority-aware suspension and later resume of background blockers before treating scarce-resource deferral as unavoidable. Infrastructure errors must retain benign demand for repair/retry rather than presenting paperwork as denial. Add default-path process/inference tests; injected inference callbacks alone do not establish this contract. This requirement applies within the existing restoration milestones and does not wait for advanced native snapshots or the full role redesign.

## Active handoff refinement (2026-09-15)

Within automatic priority-aware acquisition, eliminate arbitrary scarcity-shaped restrictions and Sudden Agent Death Syndrome before broader restoration. Managed workers receive a generous output allowance derived consistently through policy, proxy, harness, and backend; a terminal length outcome resumes the exact retained session automatically and repeated failure escalates as an emergency rather than success. Review hardcoded context, output, batching, concurrency, retry, lifetime, and recovery limits against observed Strix Halo capacity. Keep a restriction only with measured physical/protocol evidence and durable continuation behavior.

The immediate measured sequence is: qualify the forced llama.cpp 512/128 batch settings against upstream defaults and remove or justify them; remove the stale saved Qwen reasoning cap during reload; finish unloaded-model routing by resolving only the metadata needed for physical fit; then replace terminal executor time/output ceilings with retained queued continuation. Existing tests may validate changes, but MVP work prioritizes production code and does not add regression tests by default.
