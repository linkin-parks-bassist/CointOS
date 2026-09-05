# CointOS MVP execution memory

Maintained by Astra (Codex `/root`) from 2026-09-05. This repository is David's
personal orchestration infrastructure. Keep professional and customer material out.

## S0 source boundary

David approved implementation and activation of the complete MVP suite on
2026-09-05. Merge and publication remain separately controlled. The implementation
topic is `docs/cointos-mvp-bringup`; the pre-snapshot parent is
`12b1c19b805c3814038661de3ffd039f7a033d23`.

The coherent source snapshot consists of two explicit commits:

1. the existing dirty runtime, resource-control infrastructure, configuration,
   roles, service descriptions and their focused tests;
2. the complete MVP plans/specification, decisions, maintained notes and status
   documentation.

The Git commit and root-tree identifiers are the authoritative path/digest manifest;
the ignored SDD ledger records assignments and review state. S0 used path-specific
staging and never staged ignored runtime or credential trees. The unrelated
`fix/snappy-initial-response` worktree at `/home/david/.worktrees/ecosystem-snappy`
remains untouched.

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
