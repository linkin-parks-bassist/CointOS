---
status: "unverified"
created_at: "2026-09-15T22:14:34+10:00"
scope: "CointOS project"
source: "ecosystem/models.py BASE, ecosystem/resource_control.py _lemonade_request, and config/model-policy.json inspected 2026-09-15"
---

The CointOS Lemonade management API defaults to `http://127.0.0.1:13305`.
`ecosystem/models.py` reads `LEMONADE_BASE_URL` to override that default;
`ecosystem/resource_control.py` currently uses the same default directly for
management requests. The managed inference backend exposed to OpenCode is
separate and defaults to `http://127.0.0.1:13305/v1`, while the policy proxy
defaults to port 13306.

Use `/api/v1/health` on the management base for Lemonade residency and backend
records. Per-model llama.cpp servers have their own dynamic ports, such as 8001
or 8002, and expose `/props`, `/slots`, and `/metrics`.
