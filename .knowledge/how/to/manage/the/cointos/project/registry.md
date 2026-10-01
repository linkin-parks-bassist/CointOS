---
status: green
revised_at: "2026-10-02T00:37:33+10:00"
---

Use `cointos project list` to inspect enrollment. `cointos project add PATH [--name NAME]` enrolls an existing Git repository. `cointos project new NAME [--path PATH]` creates a repository with an initial project knowledge tree and commit before enrollment. Both accept `--main-branch`, integer `--priority`, `--disabled` and test-policy options shown by CLI help. Lower priorities run first within a lifecycle class. Disabled projects do not admit new product work; their existing registered knowledge trees still participate in gardening.

`cointos project set NAME` accepts `--main-branch`, `--priority`, `--enable|--disable` and test-policy options. Disabling stops the project's current agents uncharged and retains their tasks. `cointos project remove NAME` removes enrollment, never the repository; the daemon refuses removal while that project has waiting, running, review or queued work. Inspect and settle its frontier first. Creating a repository can leave its directory behind if initialization or enrollment fails; correct the reported Git/tree problem before enrolling it again.

Enrollment is the installed runtime's separate `config/projects.json`, not the source operational config. Installation preserves this user-managed file. The control API exposes `project-list`, `project-add`, `project-new`, `project-set` and `project-remove`; Coin and the dashboard use those same owners.

`cointos/projects.py` validates repository-root identity, project-name and path uniqueness, integer priority and supported fields, then writes a sorted candidate registry atomically before replacing the shared in-memory list. Failed persistence leaves both projections unchanged. Updates replace the affected record only after the write succeeds. The CLI/control boundary owns active-work removal checks and stopping disabled runs.

Evidence: `projects.py`, `api.py`, CLI help, `config.managed_trees` and `tests/test_projects.py`, including write-failure coverage for add/update/remove. Live control-surface and Telegram acceptance belongs to `what/is/the/live/acceptance/evidence/for/cointos.md`; mechanism tests alone do not establish it.
