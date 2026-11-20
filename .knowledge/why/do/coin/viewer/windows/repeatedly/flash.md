---
status: green
revised_at: "2026-11-20T18:07:31+11:00"
---

When viewer opening is enabled, viewers.look_after allocates a window while Coin is active. A disappearing process becomes eligible for replacement after its opening reservation expires. A startup exception can therefore repeatedly open and close desktop windows.

cli.automatic_coin_profile previously called split on a null live owner tag, raising AttributeError before the automatic slot could render. coin_view_state likewise called startswith on nullable live/thought owner tags. Both now treat absent/null tags as unowned: PID-based profile selection remains available and unowned preview text is suppressed. tests.test_cli_terminal covers these cases; its 13 tests pass against source and installed code.

`cointos view --off` disables further window openings without stopping Coin. Automatic opening was disabled to contain the user-reported desktop disruption and remains off. Only cli.py was deployed; no daemon or Coin restart was needed. The reopening mechanism and nullable-owner failure are established, but the original flashing window's traceback was not captured. No claim of sustained viewer reliability follows from these checks.
