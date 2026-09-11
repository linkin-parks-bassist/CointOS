# CointOS MVP design inputs

Maintained by Astra (Codex agent `/root`), 2026-09-05, during David's design
discussion. These are confirmed inputs and open questions, not an approved
implementation plan. No runtime behavior has changed in this discussion.

## Confirmed direction

- David wants a working MVP with survival modes, OOM prevention, dynamic model
  scheduling and resource management, autonomous and spontaneous agent spawning,
  and continual improvement of CointOS and its stability.
- A reasonably capable, stable Telegram frontend and useful local GPU work are
  central outcomes. Basic operation and the essential survival mechanisms precede
  exhaustive hardening. The narrow live bridge in note 0011 is a bootstrap
  milestone; the requested MVP also includes the autonomous maintenance loop.
- David requests a Janitor role and finds Steward too diffuse.
- David assigns small code cleanups to a separate Gardener role, explicitly
  excluding them from Janitor's remit.
- David requests Documenter: observe existing files/logs/environment and record
  what is found. Adding further roles must remain easy and require no scheduler
  or executor source changes for ordinary role additions.
- David reaffirmed the three binding operating principles: Coin stays available,
  no OOM, and seamless handovers across dynamic apparently arbitrary contexts.
  Context continuation is independently mandatory; only contact depends on no OOM.
- After tests and independent review, request David's approval through
  Cointelprofessional before activating self-improvement changes.
- Role priorities must be enforced by inference scheduling and resource control:
  Sole Survivor highest, then Coin, then small health inspectors, then large health
  inspectors, then reasonably ordered other roles. Coin's capacity reserve remains
  protected even though Sole Survivor has the highest schedulable rank.
- Keep operational variables modifiable through configuration. The existing timing
  owner already uses standard-library configparser; reuse standard parsers and keep
  semantic validation/reload handling rather than writing a custom config language.
- David explicitly includes agent-agent communication in the MVP. Preserve the
  existing direct, role-local, global and Coin addressing contract, live boundary
  delivery, meaningful acknowledgement and authorized control messages from note 0003.
- Agents should learn about their assigned environment from durable notes and
  actual files, logs, and other existing evidence; identify useful work; and either
  make progress within their authority or record what should be done. They should
  not depend exclusively on receiving a fully selected task.

## Existing role intent to preserve during design

`0004-v1-bootstrap-field-report.md`, under "Known debt and dangerous artifacts",
records David's earlier distinction: Innovator proposes structural improvements
but does not implement; Speculator records unconstrained observations and musings
without turning them into implementation claims. Note 0007 retains these as
planned roles. Neither currently has a role file.

## Proposed resolution for David's review

The [complete design](../docs/specs/2026-09-05-cointos-mvp-design.md)
and [task index](../docs/plans/2026-09-05-cointos-mvp-index.md) now own
the proposal. Janitor maintains notes/artifact organization; Gardener handles small
code cleanup; Refactorer handles larger accepted structural work. Steward has no
recurring MVP assignment. Discovery records distinct observations/proposals/patches
and explicit partial work. A single due selector deduplicates bounded roles/scopes;
the shared resource owner admits execution. Isolated candidates pass independent
verification and exact Coin approval before a separate installed manager activates
or rolls back them. These are proposed resolutions, not authorization to implement.

Current deliverable: replace the old delivery sequence with concrete complete-MVP
plans and bounded task packets for GPT-5.6 Sol at medium effort and local workers.
Local workers use the largest safely feasible model/context, short stoppable tasks,
and observed completion before Codex begins smoke tests. Preserve existing
uncommitted implementation work. The new proposed specification is
`docs/specs/2026-09-05-cointos-mvp-design.md`. The old seven plan pages
are compact obligation-to-task mappings, not parallel execution checklists. Only
planning documents changed; no code, runtime state, services or model allocations
were changed. Bounded local extraction used the already loaded model; it did not
establish that this was the largest model safely feasible for implementation.
