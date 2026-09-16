---
status: "unverified"
created_at: "2026-09-14T23:21:13+10:00"
scope: "local"
source: "ecosystem/roles.py and telegram.py; failing assertions in test_executor.py, test_intake.py, test_local_intent.py reviewed 2026-09-14"
---

ecosystem/roles.py reads the current ~/AGENTS.md and cli.ROOT/AGENTS.md into Binding workspace instructions and Binding ecosystem repository instructions sections when preparing a task. ecosystem/telegram.py includes ~/AGENTS.md and roles/_control-plane.md in FAST_SYSTEM at module import. Integration tests must assert the actual current instruction text is injected, not historical headings or retired policy sentences; changing global instructions must not require reinstating old policy to pass CointOS tests.
