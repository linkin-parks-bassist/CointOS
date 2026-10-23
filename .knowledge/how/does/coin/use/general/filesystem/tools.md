---
status: green
revised_at: "2026-10-24T02:08:14+11:00"
---

Coin operates the workstation through Bash commands and filesystem tools. coin.py exposes run_command(command, cwd?, timeout?), runs Bash as the local user, captures stdout/stderr and returns the actual exit code and success flag. The default working directory is the user's home. Commands run to completion unless a timeout is supplied.

coin_files.py owns fs_list/stat/read/search/mkdir/write/copy/move/remove and fs_transfer. Paths may be absolute, home-expanded or relative to the working directory. Search matches filename globs and optional literal text without following directory symlinks. Reads support UTF-8 text and line ranges. Atomic writes publish fsynced files; overwrite=true replaces existing files. Copy/move preserve existing destinations; nonempty-directory removal uses recursive=true.

fs_list returns sorted pages of at most twenty entries with total_entries, offset and next_offset. A partial page does not prove absence. fs_transfer copies or moves regular non-symlink files selected by filename glob, preserving basenames and existing destinations. Normal completion is default; verification=hash compares bytes before removing moved sources. Failed files are reported while other files continue. Successful routine operations need no repeated recounting.

Use kt tools to maintain knowledge and CointOS controls to manage running work. Coin must not claim a record saved, logged, filed, added, updated or corrected until the appropriate on-disk change succeeds. Chat history is not the requested record; failed writes must be reported as not recorded. The system prompt identifies the active COIN_STATE conversation archive directory and conversation-<user>.jsonl naming. Rolling prompt history is a recent window; earlier messages can be retrieved from the archive. Coin loads role/settings at startup, so copied changes require a Coin-only refresh preserving durable intake.

Focused tests cover file operations, aliases, recursive operations, bulk moves/collisions, pagination, atomic writes, and real Bash effects with stdout/stderr and nonzero status. These establish tool behavior; native filing and history-recovery judgment require separate verification. Standing photo routing retains its focused owner.
