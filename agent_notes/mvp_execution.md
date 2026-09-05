# CointOS MVP execution memory

Maintained by Astra (Codex `/root`) from 2026-09-05. This repository is David's
personal orchestration infrastructure. Keep professional and customer material out.

## S0 source boundary

David approved implementation and activation of the complete MVP suite on
2026-09-05. Merge and publication remain separately controlled. The implementation
topic is `docs/cointos-mvp-bringup`; the pre-snapshot parent is
`12b1c19b805c3814038661de3ffd039f7a033d23`.

The coherent source snapshot consists of two explicit commits:

1. `c7ba854152d6220b3f806b17c357aeb5708750f4` (root tree
   `937f449a72034e2c1ab19cfdbac366c47105714f`): the existing dirty runtime,
   resource-control infrastructure, configuration, roles, service descriptions
   and their focused tests;
2. `9f95ee0a7359bf9b0f16e480a9f36492cb733684` (root tree
   `4983eb1ac6ca6cf94786dc87f45f33fd215ad031`): the complete MVP
   plans/specification, decisions, maintained notes and status documentation.

The Git commit and root-tree identifiers are the authoritative path/digest manifest;
the ignored SDD ledger records assignments and review state. S0 used path-specific
staging and never staged ignored runtime or credential trees. The unrelated
`fix/snappy-initial-response` worktree at `/home/david/.worktrees/ecosystem-snappy`
remains untouched.

The live resource record was still latched in `emergency` during S0, with Coin's
4B model and an idle 27B model resident. The coordinator therefore deferred Q1's
optional local inference substep: running ordinary local work through the existing
bypass would violate Sole Survivor exclusivity before R1 supplies the new admission
owner. Q1 remains a Sol-medium TDD task; short Halo work begins only from an admitted
state and remains required for later concrete substeps.

Baseline evidence before the snapshot: `python3 -m unittest discover -s tests -v`
ran 324 tests with zero failures in 13.154 seconds; `git diff --check` returned zero.
This is offline repository evidence, not live service, Telegram, model-capacity or
OOM evidence.

## Execution invariants

- Coin availability and desktop/OOM reserve dominate worker throughput.
- Context capacity is a lease; durable task identity and destination-sized handoff
  survive model and window changes.
- Every worker and smoke owner is recorded. Smoke starts only after worker,
  process-group, backend request and inference-lease exit are observed.
- One canonical contact route, admission owner and activation route replace the
  rejected parallel semantics at their cutovers.
- Future agents update this note with compact accepted milestones and current
  boundaries; detailed task churn stays in the ignored SDD ledger.
