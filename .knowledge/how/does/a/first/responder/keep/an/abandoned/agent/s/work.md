---
status: green
revised_at: "2026-11-02T18:23:12+11:00"
---

To carry on in place, hold and revise the assignment. `lifecycle.refresh_assignment` restarts the same task with a fresh budget and a new session. `git.add_worktree` reuses an existing checkout, and `lifecycle.retire` keeps a settled task's checkout when it has uncommitted work (`retired: kept: uncommitted work`), so the files survive. An identical revision does not refill the budget, so the brief must change.

A newly dispatched agent cannot take over that checkout. It starts on its own branch from main, its writes are confined to its own checkout, and uncommitted files are not in git. It can read another checkout by path, so a brief can name the path and the parts to copy.

`cointos transcript TASK` writes a task's complete agent record to a file: all its sessions with reasoning, words, tool inputs and tool outputs, read from OpenCode's database at `~/.local/share/opencode/opencode.db`. Each run's `events.jsonl` omits reasoning. Piped `opencode export` output was truncated at 73,718 bytes in one check. The command ran inside the real write confinement on a 278-message session, producing 1.2 million characters.

Evidence: `tests/test_transcript.py`, and the source of the functions named above. A live First Responder has not yet used either route.
