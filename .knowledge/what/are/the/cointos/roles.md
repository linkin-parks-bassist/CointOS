---
status: "green"
revised_at: "2026-09-27T00:58:13+10:00"
---

Roles come in three classes. Role wording lives in `roles/`. A spawned worker, manager or steward's prompt is `roles/_base.md` (shared by every agent), then its role file, then its assignment. David owns the role wording; the files are first drafts.

- **Steward class:** keeps the system alive and healthy.
  - **Coin** (`roles/_control-plane.md`): Cointelprofessional, David's Telegram remote control and contact. Coin is a separate service and uses this prompt directly, not the OpenCode base-role launch.
  - **Steward** (`roles/steward.md`): routine checks and maintenance of CointOS itself. Scheduled only when `maintenance_project` is present in configured `projects`; sandbox-only scope currently excludes it.
- **Managerial class** (`roles/manager.md`): keeps a project's work queue full of the right things in the right order. It breaks drafted ideas into queued items, surveys projects for next steps, and reviews finished work. Managers decide *what*.
- **Worker class** (`roles/worker.md`): carries out one queued item (implement, check, commit, merge) and updates its leaf. Workers decide *how*.

Roles diversify within each class as practice shows the need. `roles/sole_survivor.md` is an inactive design sketch, retained for reconsideration rather than scheduled work. The guard performs bounded mechanical recovery; David brings in a stronger remote agent for catastrophic diagnosis and repair.

**Queues** live in each project's own knowledge tree (`~/Projects/<repo>/.knowledge`):
- `what/is/urgent/<item>.md` and `what/is/queued/<item>.md` hold work items;
- `what/is/drafted/<item>.md` holds David's drafted ideas.

The current spawner resumes waiting tasks before scanning for urgent/queued items, drafted ideas, periodic surveys and maintenance. Workers and managers are active implementations; role classes here describe responsibilities, distinct from scheduler priority classes.

An item leaf's first nonblank answer line (after metadata) is its status (`Status: queued | in progress | blocked | done | drafted`). The rest is the item's current brief.
