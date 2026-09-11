---
verified_at: '2026-09-11T16:37:17+10:00'
verified_by: codex /root
scope: project local
source: David request 2026-09-11; filesystem and Git inventory during directory migration
verification: Verified 566 ignored evidence files occupy 29 MB under
  /home/david/.CointOS/development/sdd and the two versioned reports are under
  docs/reports/sdd.
review_when: Recheck when development evidence retention or the CointOS runtime
  layout changes.
---

Generated development packets, transcripts, diffs, and viewer records live under
`/home/david/.CointOS/development/sdd`; they are runtime evidence, not repository
source. The two reports intentionally kept under version control live in
`docs/reports/sdd/`. Design documents and execution plans live directly under
`docs/specs/` and `docs/plans/`.
