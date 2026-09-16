---
status: "unverified"
created_at: "2026-09-14T23:20:24+10:00"
scope: "local"
source: "ecosystem/conversation.py, telegram.py, control_worker.py; tests/test_control_turns.py and test_conversation_projection.py reviewed 2026-09-14"
updated_at: "2026-09-14T23:21:34+10:00"
---

Telegram transport and deep workers store distinct conversation source IDs using telegram-N:user, telegram-N:front, telegram-N:deep and telegram-N:disaster. The base telegram-N identifies the durable control turn; the suffix distinguishes records for deduplication and history boundaries. conversation.append now validates source IDs separately and accepts only canonical IDs or the four supported suffixes. reply_to remains strictly canonical. Lifecycle projections resolve the base turn while retaining the full record source ID for provenance and deduplication. Regression coverage verifies distinct front/deep records, duplicate ingress suppression and invalid suffix rejection. Existing unsuffixed canonical source IDs remain supported.
