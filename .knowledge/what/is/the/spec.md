---
scope: project local
source: "David explicit CointOS work-dissolution vision and small-local-task constraint 2026-09-15"
review_when: Recheck when repository requirements or the proof-verifier contract changes.
status: "unverified"
updated_at: "2026-09-15T09:10:54+10:00"
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

Restoration sequencing: managed live parallelism comes first, then live preemptive Cointelprofessional with bounded remote operations, then full-spec implementation. A useful first restoration may use bounded concurrency and normal OpenCode session recovery; it must not silently shrink promised per-agent contexts or claim exact native state restoration. Detailed milestone acceptance is in `what/is/the/plan.md`.

Deployment contract: source at `~/Projects/CointOS`; an installer deploys all required executable code/configuration/prompts/support assets into `~/.CointOS`. Services run installed assets independently of the checkout. Upgrades preserve mutable state, logs, secrets and recovery artifacts. Standalone KT is a core integrated dependency with independent ownership. Detailed contracts: `what/is/the/intended/cointos/installation/layout.md` and `how/should/standalone/knowledge/trees/integrate/with/cointos.md`.

Allocation usability contract: automatically acquire resources for benign authorized inference. Contention is handled by priority, queueing and recoverable suspension, with sole survivor above Cointelprofessional above user agent sessions above background work. Those priority classes must practically never be blocked by lower-priority work. Terminal rejection is reserved for suspicious/unauthorized requests or a physical shortfall that cannot be resolved through priority and reclamation. Internal lease/credential provisioning and observation repair belong to CointOS; they are not operator prerequisites. Detailed scheduling authority and suspension behavior are in `what/is/intended/agent_scheduling.md`.

Working-model contract: local models receive only small concrete tasks, including one bounded step of abstract architectural decomposition. Broad work is progressively dissolved by chunkers with reviews and abstraction barriers, GPU-scheduled execution and Cointelprofessional feedback. The direct vision is owned by what/is/architecture/of/cointos.md; detailed stages/contracts remain design work.
