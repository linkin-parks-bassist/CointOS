---
status: green
revised_at: "2026-09-20T08:44:30+10:00"
checked_at: '2026-09-11T18:43:14+10:00'
---

CointOS still lacks one accepted, idempotent command that pauses intake, drains or
checkpoints live work, reconciles durable records, optionally unloads inference,
and reports whether the host is safe to reboot or power off. Do not infer that this
workflow exists from older plans. Until implemented and tested, establish live
owners and state explicitly before shutdown rather than inventing a procedure.
