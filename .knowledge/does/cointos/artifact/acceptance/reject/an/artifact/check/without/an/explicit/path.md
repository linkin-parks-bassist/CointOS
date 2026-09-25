---
status: green
revised_at: "2026-09-26T03:22:58+10:00"
verifiable: "true"
---

`ecosystem.acceptance.artifact_failure` returns `acceptance failed: artifact acceptance item 0 has no explicit path` for an artifact check with no path.

Proof:

```bash
python3 -B -c 'from ecosystem.acceptance import artifact_failure; assert artifact_failure({"acceptance": [{"kind": "artifact"}]}) == "acceptance failed: artifact acceptance item 0 has no explicit path"'
```
