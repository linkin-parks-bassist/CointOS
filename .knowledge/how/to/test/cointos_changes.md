---
verified_at: '2026-09-11T15:40:39+10:00'
verified_by: codex /root
scope: project local
source: docs/operations.md; docs/core-engineering-principles.md; python3 --version; python3 -m pytest --version; focused unittest command run 2026-09-11
verification: Confirmed /usr/bin/python3 is 3.12.3, pytest is not installed for it, and test_context_layout.py passes 12/12 through unittest discovery.
review_when: Recheck after Python environment/dependency changes or test-runner policy changes.
---

Use standard-library `unittest` in the current repository environment. Run the
narrow owner first:

```bash
python3 -m unittest discover -s tests -p 'test_<owner>.py' -q
```

The main unit-test discovery is:

```bash
python3 -m unittest discover -s tests -q
```

New tests are module-level functions collected by `load_tests` with
`unittest.FunctionTestCase`; do not add test classes. As observed on 2026-09-11,
`/usr/bin/python3 -m pytest` fails because pytest is not installed. A plan that
spells a pytest command does not prove the runner exists; use the equivalent
focused unittest command unless the environment is deliberately changed. Run
specific `tests/integration/test_*.py` modules separately when the changed boundary
requires process-level evidence; do not imply unit discovery covered them.
