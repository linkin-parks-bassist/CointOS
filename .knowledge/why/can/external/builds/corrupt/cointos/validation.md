---
status: green
revised_at: "2026-10-14T23:54:37+11:00"
---

Executed-process flock serializes CointOS commands across daemon death but cannot protect shared outputs from external builds. `tests/test_external_validation.py` reproduces false-green validation: an external compiler overwrites the failed candidate's executable while the lock is held; suite reports no caused failures with unchanged Git. A corrected checkout-local executable survives the same overwrite and restores the expected failure. Pigen compiles/executes fixed host /tmp binaries. Native user-unit PrivateTmp starts successfully but leaves host /tmp and /var/tmp visible. User namespaces are denied by host policy; no effective runner namespace is established. Repair requires project-owned unique outputs through ordinary test-contract gates.
