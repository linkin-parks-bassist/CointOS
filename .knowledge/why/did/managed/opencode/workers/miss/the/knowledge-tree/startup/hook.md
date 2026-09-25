---
status: green
revised_at: "2026-09-20T09:45:11+10:00"
checked_at: '2026-09-20T09:46:48+10:00'
---

Root cause: the installed observable launcher started every OpenCode server with `serve --pure`. OpenCode `serve --help` defines `--pure` as running without external plugins, so the installed knowledge-tree plugin could not inject its complete `kt boot` block in those managed sessions. Two affected workers attempted partial manual initialization. Active AGENTS files and generated prompts also duplicated bootstrap instructions.

Source and installed `scripts/opencode_observable.py` now omit `--pure` from the server command; real-server boundary checks pass. Active home, project, and installed AGENTS files were retired, and fresh worker prompts contain only the task text. The hook owns bootstrap. A direct plugin system-transform invocation produced one 9498-byte startup block containing the marker, local orientation, and final proof summary. Fresh managed task-73e862421c6f4c4e reported receiving the complete boot through the final `green=136 yellow=0 brown=0` summary. The real server loaded the plugin and direct KT reads succeeded. Exact system-context contents were not independently captured outside the worker transcript.

The current source and installed OpenCode adapter inject the complete boot context automatically and have no command guard. David clarified that agents need no additional bootstrap rule or tool policing when the hook delivers the knowledge in context. Adapter integration checks pass. A server already running at the time of this change retains its earlier plugin until restarted.
