---
verified_at: '2026-09-11T21:04:42+10:00'
verified_by: opencode
scope: project local
source: roles/*.md; tests/test_role_path_portability.py; David task instruction 2026-09-11
verification: Grep shows all eight helper-script references in roles/ use the
  ~/agent-ecosystem/scripts/ spelling with no /home/david/ paths remaining;
  the focused test passes 3/3 via python3 -m unittest.
review_when: Recheck if role-prompt path convention changes or the portability
  regression test is moved, renamed, or removed.
---

Role Markdown in `roles/` refers to repository helper scripts with the portable
spelling `~/agent-ecosystem/scripts/<name>` (for example
`~/agent-ecosystem/scripts/install-package` and
`~/agent-ecosystem/scripts/tell-david`), never a fixed `/home/david/...` absolute
path, because role prompts are advisory instructions an agent may run under a
different checkout or home layout.

`tests/test_role_path_portability.py` is the regression guard: it fails if any
`/home/david/` path reappears in `roles/*.md` and checks the portable spelling
stays in the six roles that reference helper scripts. Keep new role-prompt script
references in the `~/` spelling so the test keeps them honest.

The same convention extends to Python-generated task instructions in
`ecosystem/*.py`; see
[`../agent_facing_strings/use_home_specifiers.md`](../agent_facing_strings/use_home_specifiers.md).
