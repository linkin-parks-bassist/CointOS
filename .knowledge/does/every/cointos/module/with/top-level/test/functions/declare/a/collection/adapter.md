---
status: green
revised_at: "2026-09-26T06:15:19+10:00"
verifiable: "true"
---

Yes. Every `tests/test_*.py` module containing a top-level `def test_*` or `async def test_*` also has a top-level `def load_tests`. The predicate checks this structural condition only; it does not prove adapter completeness or test success.

Proof:

```bash
test -n "$(rg -l '^(async )?def test_' tests -g 'test_*.py')" && test -z "$(comm -23 <(rg -l '^(async )?def test_' tests -g 'test_*.py' | sort) <(rg -l '^def load_tests' tests -g 'test_*.py' | sort))"
```
