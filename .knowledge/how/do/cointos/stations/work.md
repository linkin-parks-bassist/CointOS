---
status: green
revised_at: "2026-11-02T10:34:34+11:00"
---

A station is where an agent works and what it can reach: (directory, tools). Every agent has one; `cointos/stations.py` owns the concept.

The directory is the task's `worktree`, so a factory agent's station is its checkout and no second copy of the path exists. `tools` lists configured MCP servers (from the user's OpenCode config) beyond the knowledge-tree and CointOS tools every agent has, or `*` for all. Factory agents have none. Coin's station is the user's home with everything.

**Requesting one.** `run_agent`, a wake's `agent`, and `cointos agent run --directory DIR --tool NAME` take a station. Only Operators can be placed in a directory. An unknown tool refuses, naming what is configured. A directory must exist, is resolved to its real path, and cannot combine with a project or the control ability. A project Operator may still receive tools.

**Boundaries.** A stationed Operator has place `system`, no branch, and a worktree outside the runtime; `stations.stationed` derives this, so no flag exists. Its edit tools and Landlock writes are confined to the directory, plus the run directory, temporary directories, OpenCode state and knowledge-rewrite state. The directory need not be a Git repository. Settling such a task never touches the directory. Reads stay as broad as other agents'. A spawned Operator gets no tool its spawner lacks, and a stationed agent's children stay inside its directory.

**Coin.** `mcp_tools` and `mcp_call` reach configured local servers through `kt_mcp.connect`, opened lazily so the fixed tool prefix stays stable. A call is bounded by the server's configured `timeout`, or `timeouts.mcp_call_seconds`; a timeout kills the server and the next call reopens it. Remote servers need an agent with that station tool. The knowledge server stays on its own session, so "everything" excludes the access tools, which remain the user's decision.

Available tools do not settle data access: a server's own policy still applies. Stdio servers run inside their agent's write confinement, so one that writes outside its allowed paths fails there.

Evidence: `tests/test_stations_and_recurring_wakes.py` covers grants, refusals, real Landlock confinement in a non-Git directory, spawning limits and hung servers. Native runs under a live daemon remain unobserved until deployed.
