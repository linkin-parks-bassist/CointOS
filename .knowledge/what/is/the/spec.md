---
status: green
revised_at: "2026-09-26T08:11:26+10:00"
---

The repository's product contracts live under `what/is/intended/`, with the public
vertical-slice description in `README.md`. Standalone knowledge trees own proof
verification through `kt prove`; CointOS must use that public CLI rather than
maintain a separate verifier. It checks the exact current-directory knowledge root
(or an explicitly permitted root), validates marked proofs and selects optional
semantic path-component tokens. Success is quiet by default; `--verbose` lists
checks. Invalid structure or failed execution fails; an empty selection succeeds.
It does not discover parent roots. The canonical procedure is
`global:how/to/check/knowledgetree/proofs.md`.

David amendment 2026-09-14: the existing roles are to be mostly scrapped and rebuilt from nearly scratch, because much intended role behavior is now subsumed by general knowledge-tree machinery. Treat this as the target design direction; the replacement contract remains to be worked out. See `what/is/the/intended/replacement/for/existing/agent/roles.md`.

David clarification: roles remain necessary, but their responsibilities will be substantially redesigned compared with the current written roles, accounting for general behavior already supplied by knowledge-tree machinery. This direction does not call for a role-free architecture.

David amendment: defer custom context handoffs and fresh-session continuation; OpenCode owns compaction within retained sessions. Native inference snapshots remain a separate coarse-grained scheduling goal. See `why/are/cointos/context/handoffs/deferred.md`.

Every observable local launch must derive fresh backend/client capacity, constrain it to any admitted lease, override stale context/input/output claims, and verify OpenCode resolved limits before inference. Normal OpenCode compaction is enabled on the qualified selected model. Native snapshots preserve the current inference working state; normal compaction may deliberately change that state before a snapshot. Snapshotting and compaction are separate mechanisms. Implementation details and remaining reconfiguration limits are in `why/must/opencode/launch/capacity/be/verified/end/to/end.md`.

Availability contract: a request to stop development does not authorize leaving a deployed CointOS generation in a preventably broken or emergency-stuck state. The Sole Survivor is an automated, dedicated incident-diagnosis and repair mechanism. A failed survivor must trigger durable, rate-limited escalation to another recovery attempt while resources permit; failure is not a normal steady state or a handoff that requires David to notice and restart it. The guard must keep unsafe ordinary work gated, preserve failure evidence, and allow recovery only after checked postconditions. Physical unsafety or failed infrastructure can delay escalation, but must remain visible and retryable rather than being treated as completion.

Restoration sequencing: managed live parallelism comes first, then live preemptive Cointelprofessional with bounded remote operations, then full-spec implementation. A useful first restoration may use bounded concurrency and normal OpenCode session recovery; it must not silently shrink promised per-agent contexts or claim exact native state restoration. Detailed milestone acceptance is in `what/is/the/plan.md`.

Deployment contract: source at `~/Projects/CointOS`; an installer deploys all required executable code/configuration/prompts/support assets into `~/.CointOS`. Services run installed assets independently of the checkout. Upgrades preserve mutable state, logs, secrets and recovery artifacts. Standalone KT is a core integrated dependency with independent ownership. Detailed contracts: `what/is/the/intended/cointos/installation/layout.md` and `how/should/standalone/knowledge/trees/integrate/with/cointos.md`.

Allocation usability contract: automatically acquire resources for benign authorized inference. Contention is handled by priority, queueing and recoverable suspension, with sole survivor above Cointelprofessional above user agent sessions above background work. Those priority classes must practically never be blocked by lower-priority work. Terminal rejection is reserved for suspicious/unauthorized requests or a physical shortfall that cannot be resolved through priority and reclamation. Internal lease/credential provisioning and observation repair belong to CointOS; they are not operator prerequisites. Detailed scheduling authority and suspension behavior are in `what/is/intended/agent_scheduling.md`.

Working-model contract: local models receive only small concrete tasks, including one bounded step of abstract architectural decomposition. Broad work is progressively dissolved by chunkers with reviews and abstraction barriers, GPU-scheduled execution and Cointelprofessional feedback. The direct vision is owned by what/is/architecture/of/cointos.md; detailed stages/contracts remain design work.

MVP policy clarification 2026-09-16: CointOS is currently a single-owner, local-machine system for David's use and demonstration. Establish the functioning general system and learn its decomposition before adding containment, internal authorization, policy-adoption ceremonies, or defensive execution gates. Resource management remains essential scheduling: account for actual finite capacity, prioritize, queue, suspend, reclaim and resume. It is not an internal firewall. Keep malformed-input and protocol-consistency validation, but missing workspace registration, authority snapshots, task contracts or similar paperwork must not refuse ordinary local work. External Telegram allowlisting may remain at the transport edge without creating repeated internal authorization layers.
