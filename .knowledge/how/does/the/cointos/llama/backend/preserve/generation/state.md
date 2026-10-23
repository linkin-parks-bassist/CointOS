---
status: green
revised_at: "2026-10-14T23:34:40+11:00"
---

`/apply-template`, `/tokenize`, `/detokenize` translate messages/tokens; `/completion` prepares prefixes and returns bounded vectors. Slot save/restore serializes to `/dev/shm` and uses tensor copies, not pointer swaps. The [resident-slot prototype](../../../../../../../to/benchmark/cointos/context/handoffs.md) is not deployed.

Stock b10723 saves target state only. The selected independent-MTP path appends draft KV and its cross-batch `pending_h` embedding in a versioned trailer. Native file size includes both for CointOS accounting/spill. Stop-tail trimming selects the retained boundary row; a fresh sequence zeroes its initial carryover. Malformed trailers reject the restore and clear the slot. Legacy target-only files remain usable with cold draft state; they cannot recover omitted history. New paired saves preserve subsequently accumulated draft context without forcing a full reread. Old native readers ignore the trailer, supporting rollback. Erase clears both contexts. DFlash and other speculative paths retain their existing snapshot behavior; target-token retention alone does not prove draft continuity.

The hybrid recurrent/attention model reuses a state only when its tokens prefix the next prompt. Preparation stops one token short; verification submits the full real prompt. Equal-length verification after restore would require an unavailable earlier checkpoint and discard cache. Strict extension establishes the checkpoint for generation's last-token reevaluation. Retained prefix derives from `tokens_cached` and complete prompt/output vectors, never output count alone. Unknown speculative tails are cold while valid replies are delivered. The selected stop patch trims supported rejected/stopped tails with one bounded rollback. A stream cut can leave unseen state: resume from a committed checkpoint, not an assumed exact suspended state.
