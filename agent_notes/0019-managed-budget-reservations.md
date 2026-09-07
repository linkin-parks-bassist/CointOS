# Managed budget reservations — 2026-09-07

Approved R5 shared budget enforcement, independent of contact design amendment.
Local BUILD workers are not subject to new arbitrary wall-clock limits. Root
runtime remains untouched; worktree /home/david/.worktrees/cointos-mvp-budget-reservations
on fix/mvp-budget-reservations starts at a1afa92.

Sieve read-only counter map finds no production call of discovery_evidence or
read_evidence, and no evidence-items charge. This is an unwired discovery boundary,
not proof of observed live repeated evidence reads. Child admission already
deducts reservations from remaining_budget; adding usage.children without changing
the comparison representation would risk double charging. Do not apply that
suggested repair blindly. The map's blanket time/output-correct claim excludes
concurrent/delegated reservations and is not full R5 acceptance.

Astra reproduced a concrete A1/R5 seam: narrow_contract accepts child task_seconds500
when parent ceiling900 already has durable budget_usage.task_seconds600. Combined
own consumption plus child reservation1100 exceeds900. A1 compares only reservation
ceiling, ignoring durable consumption. No runtime records or model calls needed
for the pure temporary-fixture probe.

local-r5-spent-reservation-red creates <=2 plain tests: pure narrowing and real
enqueue/delegation, rejecting overspend while preserving exact-fit and idempotent
replay. Test-only RED is not a completed fix. Later repair must keep a consistent
reservation-ceiling/cumulative-usage representation; live in-flight freshness and
evidence-tool enforcement are separate follow-ups, not silently claimed solved.
Baseline focused25 tests passed before work. 8c6bde2 adds two regressions; Astra
reviewed and independently reproduced both expected overspend failures. A fixture
gap would obscure the later second-child test: child consumed all other quotas.
Next local-r5-spent-reservation-fix first narrows those fixture quotas, then compares
child task time against reservation ceiling minus durable own consumption ONLY.
No persistent debit for own usage (avoids double charge), no usage.children write,
no executor/CLI protocol change. Exact-fit/replay preserved; malformed durable time
refused. Tests must use automatic collection for added plain-function cases.
d5feb3f implements the bounded check and corrected fixtures. Astra independently
passed28 focused tests, then caught explicit budget_usage:null treated as absence
despite the packet's present-dict requirement. A tiny Astra regression failed,
896da1e distinguishes absent from malformed null, and28 focused tests passed again.
Source review: pure admission comparison only; remaining_budget/usage unchanged,
no CLI or executor edits; exact-fit300 allowed after600/900 spent, replay does not
deduct twice, further1 refused with other quotas still available.

Full candidate verification at896da1e:592 discovered tests passed, plus33 separately
discovered integration tests passed (625 total). git diff --check clean; only
task_contracts.py and test_spent_child_reservation.py differ from base source.
The three test functions are automatically collected. Worker finished with normal
proxy revoke/R3 release. Accepted isolated repair, NOT integrated or activated in
runtime root. Contact worktree remains separate and lacks this repair.

Remaining R5/A1 work: live in-flight usage freshness, concurrent parent record
updates during delegation, consistent treatment of other spent shared counters,
actual discovery-tool wiring/accounting and genuinely bound useful handoff evidence.
These are follow-ups, not claims covered by the625-test result. Do not add usage
counters atop already-debited reservations without a consistent representation.

Astra next dispatch: local-r5-parent-write-map, read-only source investigation of
whether cached executor job persistence can lose concurrently admitted child
reservations. Deliverable is the real writer/lock sequence and smallest deterministic
composition probe; no repair authorized in this packet. Hypothesis remains unproven.
