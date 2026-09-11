---
verified_at: '2026-09-11T18:43:14+10:00'
verified_by: codex /root
scope: project local
source: git history for the former safe-powerdown agent note; docs/operations.md; current source inspection
verification: Confirmed the desired lifecycle boundary was documented but no single accepted safe-powerdown command is present.
review_when: Recheck when shutdown/drain lifecycle work is implemented.
---

CointOS still lacks one accepted, idempotent command that pauses intake, drains or
checkpoints live work, reconciles durable records, optionally unloads inference,
and reports whether the host is safe to reboot or power off. Do not infer that this
workflow exists from older plans. Until implemented and tested, establish live
owners and state explicitly before shutdown rather than inventing a procedure.
