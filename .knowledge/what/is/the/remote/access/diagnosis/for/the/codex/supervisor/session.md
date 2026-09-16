---
status: "unverified"
scope: project local
source: "Android thread/resume error and host file-lock owners 2026-09-15"
review_when: Recheck after Codex server or remote-control changes.
updated_at: "2026-09-15T00:43:58+10:00"
---

The Android app lists the supervisor but spins indefinitely on open. Its thread/resume request for 01a0a011-45a6-79b0-9378-057a1c27dea6 fails with thread-store conflict: thread already has an active writer. Host lslocks identifies Codex PID 1560372 as holding that thread writer lock, while PID 687996 holds the working remote support conversation 01a0a05c-ce12-7b40-a957-0472d8fea312. This establishes cross-process thread ownership contention as the immediate resume failure. notLoaded from the remote server must not be interpreted as global inactivity. The exact safe transfer or consolidation procedure remains to be qualified; do not delete a live writer lock or kill the supervisor to bypass it. OpenCode worker loopback binding is a separate matter.
