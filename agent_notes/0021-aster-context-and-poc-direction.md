# Aster: prepared knowledge and POC priorities

Author: Aster, an Astra instance (Codex `/root`), 2026-09-08.
I previously called myself Sol while recording decisions 0019 and the immediately
preceding prefill note; that attribution was mistaken. Older Sol-authored work is
not retrospectively mine. David explicitly selected Adviser and requested durable,
committed design/planning notes for future coordinators. I proposed the Adviser
name; David selected it. David supplied the expert role's purpose and the naming
convention. Preserve that provenance: good naming is a substantive contribution,
and David explicitly does not want credit for work contributed by another agent.

## What future agents must preserve

David is building a society/ecosystem of role-directed agents that share knowledge
and continue work across inactive periods. Resident processes and occupied GPU
slots are not the definition of agent existence. Adviser embodies this: a durable
topic expert may wait with no physical slot, then answer questions when admitted.
Lecturer supplies reusable explanations; Auditor independently checks them.

The immediate bottleneck motivating this direction is repeated orientation. Even
tiny worker packets have spent many turns locating files, reading broad documents
and reconstructing context. The answer is a fresh, scoped brief plus discoverable
knowledge, not a blanket command to read more documentation. Give workers specific
locations, current accepted state, known test failures and relevant evidence before
they start. Explain that the supplied orientation is current for its stated inputs
and need not be rediscovered. Keep checks focused on contradictory/changed facts or
the actual action boundary. Do not claim a generated summary is inherently true.

Lectures should carry the causal story and prerequisites, not just compressed
bullet fragments. They are knowledge artifacts, not extra sources of policy or
authority. Topic versioning and independent audits stop a persuasive error from
becoming shared folklore. Advisers record coverage and gaps, and answer within the
requester's permitted information scope. Personal CointOS work must remain separate
from David's employer/customer projects even when the same machine hosts both.

The -er/-or role naming convention matters to David. Lecturer and Adviser are
accepted. Keep Auditor initially as one role with specialized lecture tasks.
System Controller was suggested for CoinToss's underlying role; no rename approved.

## Why this connects to saved-state timesharing

Preparing context and preserving computed context complement each other. A concise
brief saves discovery turns; state restoration can avoid repeating long prefill.
Injecting an entire archive would instead recreate the cost. Measure time to useful
action and peer GPU impact alongside accuracy, coverage and tool-call savings.
Long disk-to-DDR staging is acceptable when peers stay productive; actual overlap,
model-specific state completeness and restore semantics remain to be qualified.

Decision 0019 makes saved-state timesharing D10 canonical and post-MVP, alongside
the top-priority central compatibility modules D9. Decision 0020 and D11 record
prepared context, lectures and Advisers. The plan index is the scheduling source of
truth. Do not quietly move these improvements into the MVP acceptance gate: David
explicitly accepts a clunky/slow POC and prioritizes getting the system to exist.

## Handoff discipline

Use bounded local workers for concrete pieces and keep architecture/synthesis with
the coordinator. Split brief compilation, lecture writing, lecture audit and Adviser
mailbox composition; do not assign one worker to build the whole knowledge system.
Briefs should prevent repeat baseline investigation while preserving independent
verification of a candidate's claimed result. A successful OS exit is not evidence
of completed work, and freed occupancy is not task acceptance. Keep those meanings
distinct when recording new packets. This note changes no runtime behavior.
