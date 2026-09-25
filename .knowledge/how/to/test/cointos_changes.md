---
status: green
revised_at: "2026-09-26T06:59:37+10:00"
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

In this checkout, bare `python3 -m unittest -q` discovers zero tests; use the explicit discovery command. Run `python3 -m unittest discover -s tests/integration -q` separately for process integration when relevant. The current explicit standard discovery passes 837 tests, including 27 checks collected through `load_tests` adapters in five function-style modules. Separate process-integration discovery passed 33, giving 870 checks across the two explicit suites.

Knowledge-tree behavior claims should carry the smallest deterministic proof that establishes the claim: one focused existing test, a tiny import/assertion, or a bounded direct smoke-check script. Because routine startup runs local proofs, keep each proof quick and never attach full discovery, integration suites, live inference, service restarts, or network-dependent checks to a leaf. Broad verification remains a deliberate operator action, not a startup-hook side effect.

The quiet summary (`Ran N tests`, `OK`, `FAILED`) is written to stderr, not
stdout. Discarding stderr, or grepping only stdout, hides the result; run with
`2>&1` when checking the summary.

Test collection is mixed: `unittest.TestCase` classes and module-level functions exposed through `load_tests` are collected, but raw `def test_*` functions without `load_tests` are silently skipped by unittest discovery. A focused discovery of `tests/test_executor_cancellation.py` previously returned zero despite four functions. The missing adapters in backend-profile policy, executor cancellation, post-close recovery, round outcomes, and pure job outcomes now collect their existing functions; their combined focused run executes 27 existing checks. This repairs suite wiring rather than authoring new regression cases. `does/cointos/unittest/discovery/collect/27/existing/safety/checks.md` has a read-only, subsecond count proof, and `does/every/cointos/module/with/top-level/test/functions/declare/a/collection/adapter.md` guards future function-style modules against missing adapters. These KT proofs do not run temporary-root cases during startup. As observed on 2026-09-11,
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

The global MVP development policy still prohibits authoring new regression tests across projects until David explicitly changes it. David's later request to integrate the test suite into KT guidance authorizes quick proofs using existing tests or tiny read-only predicates; it does not by itself authorize new regression-test authoring. Implement production code first and verify with existing focused checks and bounded direct smoke checks. Do not delete existing tests. Local workers may implement bounded changes; the coordinator reviews and runs integration checks.
