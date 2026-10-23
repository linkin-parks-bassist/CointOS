---
status: green
revised_at: "2026-10-19T23:20:14+11:00"
---

Shutdown independently attempts lane-context saving, machine-stop snapshot persistence, final ledger saving and final diagnostic flushing. A failed final ledger save still flushes the shutdown/failure events; source and installed tests/test_journal.py verify this boundary. Diagnostic persistence owns ordering, errors and the unflushed-tail limit. Installed cache persistence drains pending disk retirement outside LOCK, then rechecks and reserves actual capacity for each spill; pending deletion is not free space. Qualification passes 117 focused source/installed and 1,061 full source tests. The compatible daemon activation succeeds; machine-stop acceptance remains separate. Earlier reboot exercised PATH/order and exposed repaired saving defects; combined spill admission now reserves copies and survives eviction. Repaired reboot/halt acceptance remains open and requires separate authorization.
