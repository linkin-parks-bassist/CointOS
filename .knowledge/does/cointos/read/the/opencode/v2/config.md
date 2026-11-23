---
status: green
revised_at: "2026-11-23T13:03:15+11:00"
---

Yes. `cointos/stations.py` prefers `~/.config/opencode2/opencode/opencode.json` when present and falls back to `~/.config/opencode/opencode.json`. It accepts V2's `mcp.servers` shape and the V1 `mcp.<name>` shape, normalizes `disabled` to `enabled`, omits other disabled servers from station grants, and always keeps the knowledge server.

`cointos/opencode.py` still writes V1-shaped run settings (`mcp`, `permission`, `plugin`). OpenCode 2.3.0 migrates those to `mcp.servers`, `permissions`, and `plugins`, including nested shell/read/edit rules; a `permission.shell` key works the same as V1 `bash`. Verify a generated run config with `OPENCODE_CONFIG=<run>/opencode.json opencode debug config`.
