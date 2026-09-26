---
status: "green"
revised_at: "2026-09-26T10:53:35+10:00"
---

Roles come in three classes. Each role is a Markdown file in `roles/`. An agent's prompt is `roles/_base.md` (shared by every agent), then its role file, then its assignment. David owns the role wording; the files are first drafts.

- **Steward class:** keeps the system alive and healthy.
  - **Sole Survivor** (`roles/sole_survivor.md`): emergency custodian, started by the guard under memory pressure.
  - **Coin** (`roles/_control-plane.md`): Cointelprofessional, David's Telegram remote control and contact.
  - **Steward** (`roles/steward.md`): routine checks and maintenance of CointOS itself.
- **Managerial class** (`roles/manager.md`): keeps a project's work queue full of the right things in the right order. It breaks drafted ideas into queued items, surveys projects for next steps, and reviews finished work. Managers decide *what*.
- **Worker class** (`roles/worker.md`): carries out one queued item (implement, check, commit, merge) and updates its leaf. Workers decide *how*.

Roles diversify within each class as practice shows the need.

**Queues** live in each project's own knowledge tree (`~/Projects/<repo>/.knowledge`):
- `what/is/urgent/<item>.md` and `what/is/queued/<item>.md` hold work items;
- `what/is/drafted/<item>.md` holds David's drafted ideas.

An item leaf's first line is its status (`Status: queued | in progress | blocked | done | drafted`). The rest is the item's current brief.
