---
scope: project local
source: roles/*.md; tests/test_role_path_portability.py; David task instruction 2026-09-11
review_when: Recheck if role-prompt path convention changes or the portability
  regression test is moved, renamed, or removed.
status: "unverified"
updated_at: "2026-09-14T22:55:13+10:00"
---

Role Markdown in `roles/` refers to repository helper scripts with the portable
spelling `~/Projects/CointOS/scripts/<name>` (for example
`~/Projects/CointOS/scripts/install-package` and
`~/Projects/CointOS/scripts/tell-david`), never a fixed `/home/david/...` absolute
path, because role prompts are advisory instructions an agent may run under a
different checkout or home layout.

`tests/test_role_path_portability.py` is the regression guard: it fails if any
`/home/david/` path reappears in `roles/*.md` and checks the portable spelling
stays in the six roles that reference helper scripts. Keep new role-prompt script
references in the `~/` spelling so the test keeps them honest.

The same convention extends to Python-generated task instructions in
`ecosystem/*.py`; see
[`../agent_facing_strings/use_home_specifiers.md`](../agent_facing_strings/use_home_specifiers.md).
