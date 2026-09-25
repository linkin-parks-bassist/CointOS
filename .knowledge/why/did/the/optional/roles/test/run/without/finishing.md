---
status: green
revised_at: "2026-09-25T22:23:42+10:00"
verifiable: "true"
---

The live-control-prompt fixture supplied an initial reply that promised to check, then made its fake model request `finish_silently` on every turn. The controller rejected silence after that promise and asked for the result, so the unchanged fake response repeated indefinitely. The fixture now requests `publish_followup` with a non-empty result; the focused module terminates promptly.

Proof:

```bash
python3 -m unittest tests.test_optional_roles -q
```
