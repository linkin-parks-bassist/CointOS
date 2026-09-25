---
status: green
revised_at: "2026-09-19T23:48:16+10:00"
---

rg is ripgrep, the fast file/text search executable. On 2026-09-19 the Qwen worker in session ses_f461a9329ffeVNGi3phPu7TfOO twice ran rg and received /bin/bash: line 1: rg: command not found. The coordinator had rg only in a Codex-bundled codex-path release directory, whereas the OpenCode server PATH included ~/.local/bin and standard system directories but not that Codex directory. Installed the available ripgrep 15.2.0 executable at ~/.local/bin/rg; a shell with the worker PATH now resolves rg and prints its version. This fixes command discovery without reloading the active worker. If it recurs, check the actual worker process PATH and command -v rg in that environment; use grep as fallback if needed.
