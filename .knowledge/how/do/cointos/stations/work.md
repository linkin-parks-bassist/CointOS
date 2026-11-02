---
status: green
revised_at: "2026-11-02T18:04:02+11:00"
---

A station is where an agent works and what it can reach: (directory, tools). Every agent has one; `cointos/stations.py` owns the concept.

The directory is the task's `worktree`, so a factory agent's station is its checkout and no second copy of the path exists. `tools` lists configured MCP servers (from the user's OpenCode config) beyond the knowledge-tree and CointOS tools every agent has, or `*` for all. Factory agents have none. Coin's station is the user's home with everything.

**Requesting one.** `dispatch`, a wake's `agent`, and `cointos agent run --directory DIR --tool NAME` take a station. Only Operators can be placed in a directory. An unknown tool refuses, naming what is configured. A directory must exist, is resolved to its real path, and cannot combine with a project or the control ability. A project Operator may still receive tools.

**Boundaries.** A stationed Operator has place `system`, no branch, and a worktree outside the runtime; `stations.stationed` derives this, so no flag exists. Its edit tools and Landlock writes are confined to the directory, plus the run directory, temporary directories, OpenCode state and knowledge-rewrite state. The directory need not be a Git repository. Settling such a task never touches the directory. Reads stay as broad as other agents'. A spawned Operator gets no tool its spawner lacks, and a stationed agent's children stay inside its directory.

**Coin.** `mcp_tools` and `mcp_call` reach configured local servers through `kt_mcp.connect`, opened lazily so the fixed tool prefix stays stable. A call is bounded by the server's configured `timeout`, or `timeouts.mcp_call_seconds`; a timeout kills the server and the next call reopens it. Remote servers need an agent with that station tool. The knowledge server stays on its own session, and all its tools are in Coin's prompt.

Available tools do not settle data access: a server's own policy still applies. Stdio servers run inside their agent's write confinement, so one that writes outside its allowed paths fails there.

**Admission.** A stationed run competes for memory like other work. A new agent needs its process cap plus native state (about 20 GB), so with two agents running a scheduled occurrence can wait until one finishes; the check below waited 28 minutes.

Evidence: `tests/test_stations_and_recurring_wakes.py` covers grants, refusals, real Landlock confinement in a non-Git directory, spawning limits and hung servers. A native installed schedule wake started a stationed Operator with no model turn and re-armed; the agent wrote in a non-Git directory, was denied a write under home and reached the granted Studio server (`unknown job_id` for a fake job). Coin's own model-driven setup of a recurring agent remains unobserved.
