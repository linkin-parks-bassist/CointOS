---
status: "unverified"
created_at: "2026-09-15T00:21:22+10:00"
scope: "local"
source: "inference_proxy.py _backend_json; actual concatenation404 and helper caller contract 2026-09-15"
---

ecosystem/inference_proxy.py _backend_json validates a loopback base, opens HTTPConnection to its host/port with timeout=1, and requests the supplied absolute origin path. It does not append the path to a /v1 prefix. Therefore _backend_json(identity.backend_base, /slots) requests origin /slots; concatenating backend_base + /slots produced /v1/slots and HTTP404 in the observed local progress probe. Backend props/slot observers use the helper so addresses and paths remain separate.
