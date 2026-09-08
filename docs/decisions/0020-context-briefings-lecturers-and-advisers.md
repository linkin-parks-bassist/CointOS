# 0020: Prepared context, Lecturers and Advisers

Status: intended architecture approved by David, 2026-09-08.
Recorded by Aster, an Astra instance (Codex `/root`). Personal CointOS scope.
Provenance: David proposed layered orientation, the Lecturer/archive concept and a
durable answering subject expert. This Astra instance proposed the name Adviser;
David selected it. David regards precise naming as part of architectural taste
and explicitly requests faithful attribution rather than assigning all ideas to him.
Documentation now; implementation tracked as D11 in the post-MVP queue. This
does not add a POC gate, activate roles or expand existing worker packets.

## Intent and context layers

CointOS should make context preparation a first-class responsibility. Local workers
currently spend substantial inference and tool time finding their bearings. Prepare
the knowledge they need so bounded work starts promptly, and retain reusable
expertise across the agent population.

1. Repository orientation: maintain a live Markdown map of architecture, conventions,
   authoritative documents, important interfaces, test commands and current state.
   Distinguish stable repository knowledge from rapidly changing runtime facts.
2. Dispatch briefing: assemble immediately before dispatch for the exact task and
   workspace. Include objective, authority, evidence boundary, budget, stopping
   condition, relevant code/tests, accepted decisions, known baseline failures,
   available artifacts, active overlapping work and selected topic knowledge.
3. Topic lectures: searchable, reusable Markdown explanations with a narrative
   account of one topic, prerequisites, concrete examples, sources and limitations.
   Retrieve the relevant lecture when a worker discovers a knowledge need.

The worker-facing briefing explicitly says it was generated immediately before
dispatch, names the source revision and observation time, and instructs the worker
to use that orientation without repeating repository discovery. Trust is scoped to
the recorded sources and covered facts: freshness is not an unconditional guarantee
of correctness. Recheck only changed, contradictory or action-critical facts.
Record dirty-worktree inputs as well as the base commit when relevant; a commit
alone does not describe concurrent local changes. Runtime observations carry their
own freshness/scope. Briefings cannot grant authority beyond the task contract.

Prefer injecting selected briefing contents into the initial prompt through the
central runner adapter; a named Markdown artifact is the portable baseline when
direct injection is unavailable. Keep AGENTS.md as governing instructions and
link the knowledge entry point there when implemented; do not continually rewrite
it with per-run facts. Preserve the exact dispatched brief as evidence while the
maintained orientation may evolve. Cap selected context to the admitted task budget:
excess injection itself costs prefill and attention. Measure time to first useful
action, discovery reads, prompt size and redundant verification.

## Roles and knowledge lifecycle

Documenter records observed systems. Lecturer distils source material into a
consumable explanation of one topic. Adviser is the approved name for the subject
expert: it acquires all applicable lectures within its declared topic, preserves
that knowledge and receives questions from other agents. Narrow an oversized topic
or divide learning into bounded continuations; never silently omit lectures while
claiming comprehensive coverage. Record which lecture versions were consumed.

An Adviser is durably alive and addressable while inactive; idle waiting holds no
physical inference slot. Preserve its identity, knowledge references, mailbox and
continuation. On a question, reacquire resources, restore or reconstruct context,
answer with sources and uncertainty, and yield again. D10 computed-state snapshots
may accelerate this; saved text and references remain reconstruction evidence.
A topic specialist is not omniscient: questions outside coverage produce an honest
gap or a bounded request for further work. Replies use existing messaging contracts.
Answers must respect the requester's access scope as well as the Adviser's own.

Auditor remains one role initially. Lecture auditing is a specialized task with
independent review against original sources: factual correctness, omissions,
misleading simplifications, prerequisites, applicability and stale assumptions.
Review is bound to the exact lecture version and evidence. Revisions or changed
source dependencies trigger targeted re-review; expose draft, reviewed, stale and
superseded status. Advisers refresh or flag stale knowledge rather than extending
an old audit's authority to new text. A prose explanation is not executable policy.

Lectures need stable topic identifiers, discoverable summaries/prerequisites,
source/version provenance, scope, author and audit status. Keep Markdown as the
human/agent-consumable artifact and use explicit plain metadata for retrieval and
freshness; define the minimal representation during implementation. Do not require
a vector database or a new scheduler. Use existing role, job, mailbox, budget,
filesystem and verification contracts; vendor context injection stays at adapters.

David's naming convention is agent-role nouns ending in -er; Auditor's -or is
explicitly acceptable. Lecturer and Adviser are approved names. System Controller
is a possible future underlying role name for CoinToss, not an authorized rename.
The social metaphor describes role-directed agents; software remains ordinary
functions over explicit data, not a class/actor framework.

## Delivery and acceptance

See the D11 plan for bounded dispatch-briefing, lecture, audit and Adviser slices.
Fresh task briefs are the first useful slice; archives and Advisers build on their
provenance/freshness contracts. Coordinate with D9's runner boundary and D10's idle/
restore capabilities. Keep their top post-MVP priority and the current POC focus.

Acceptance must show a grounded fresh brief avoids redundant orientation; relevant
lectures can be found and consumed without loading the whole archive; a seeded
lecture defect is independently caught; changed sources invalidate affected trust;
an idle Adviser remains addressable without a physical slot and answers a queued
question after resumption; and an unknown/out-of-scope question stays explicit.
No implementation or runtime success is claimed by this decision.
