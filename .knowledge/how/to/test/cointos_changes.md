---
scope: project local
source: "David explicit DO NOT write regression tests during MVP bringup 2026-09-15"
review_when: Recheck after Python environment/dependency changes or test-runner policy changes.
status: "unverified"
updated_at: "2026-09-15T08:03:34+10:00"
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

Existing tests use module-level functions collected by `load_tests` with
`unittest.FunctionTestCase`; do not add test classes. As observed on 2026-09-11,
`/usr/bin/python3 -m pytest` fails because pytest is not installed. A plan that
spells a pytest command does not prove the runner exists; use the equivalent
focused unittest command unless the environment is deliberately changed. Run
specific `tests/integration/test_*.py` modules separately when the changed boundary
requires process-level evidence; do not imply unit discovery covered them.

Do not select a decorated module-level function via python3 -m unittest module.function: the loader calls the wrapper, which returns None after executing it, then raises TypeError returned None, not a test. This can obscure whether the assertion passed. Load the module's load_tests suite and filter FunctionTestCase.id() instead. In the current native module this returned16 cases and selected exactly1 live-owner case without running it:

```python
import unittest
from tests import test_managed_inference as module
suite = unittest.defaultTestLoader.loadTestsFromModule(module)
chosen = unittest.TestSuite(case for case in suite
                           if case.id() == "test_live_owner_is_untouched_by_reconciliation")
result = unittest.TextTestRunner().run(chosen)
raise SystemExit(not result.wasSuccessful())
```

Evidence: owned worker's per-name TypeError, current with_proxy/load_tests convention and coordinator suite selection16/1. Selection itself is not a passing test run.

MVP bringup policy: DO NOT write regression tests. This applies to local workers and the hosted coordinator. Implement production code first; verify with existing focused checks and bounded direct smoke checks. Do not create regression-test suites or require a failing test before making a fix. Do not weaken this prohibition into a preference or silently substitute hosted regression-test writing. David must explicitly change this policy before regression-test authoring resumes. Existing tests are not deleted by this policy.

Local workers own implementation and short handoffs. The coordinator owns review, direct verification and integration; no extra hosted/Sol agent is needed. The test-runner conventions above describe existing tests and do not authorize adding regression tests.
