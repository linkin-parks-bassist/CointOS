---
status: green
revised_at: "2026-09-26T06:58:57+10:00"
checked_at: "2026-09-26T06:49:19+10:00"
verifiable: "true"
---

Yes. Unittest collects 3, 4, 9, 7, and 4 existing checks respectively from `test_backend_profile_policy`, `test_executor_cancellation`, `test_executor_post_close_recovery`, `test_executor_round_outcomes`, and `test_job_outcomes` (27 total).

Proof:

```bash
python3 -B -c 'import unittest; from tests import test_backend_profile_policy as a, test_executor_cancellation as b, test_executor_post_close_recovery as c, test_executor_round_outcomes as d, test_job_outcomes as e; assert [unittest.defaultTestLoader.loadTestsFromModule(m).countTestCases() for m in (a,b,c,d,e)] == [3,4,9,7,4]'
```
