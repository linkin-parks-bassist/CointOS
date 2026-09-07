# Watching local workers

David requested the native OpenCode UI for future local Qwen runs on 2026-09-07.
This is the default launch arrangement, not a separate inference worker.

The existing admitted command is wrapped with:

```sh
python3 scripts/opencode_observable.py --view-record /absolute/run-specific/view.json -- \
  /home/david/.local/bin/opencode run --pure --auto --format json \
  --title PACKET --model Lemonade/Qwen3.8-27B-GGUF --dir /absolute/worktree
```

The supervisor is launched AFTER the ordinary gate, never as an admission bypass.
It starts `opencode serve --pure --hostname 127.0.0.1 --port 0 --mdns=false`, creates
or resumes the exact session, and runs the CLI attached to that server. It retains
the inherited anonymous config FD only where the server needs it. The server and
CLI remain in the admitted process group; the supervisor reaps both before exit.
Normal capacity release still requires existing independent backend-close evidence.

The private view record and a `worker_view_ready` JSONL event contain the exact
`opencode attach ... --session ...` command. Paste that command into a terminal.
The launcher assigns a reusable GNOME Terminal monitor slot automatically,
passing the complete session ID as an argument. The viewer has no
inherited config descriptor and is detached from the worker's process group.
David subsequently clarified the policy: auto-open only during an active driver
session; explicit AFK/overnight mode suppresses windows and focus changes, retaining
attachability/logs. DISPLAY/WAYLAND_DISPLAY alone cannot establish driver presence.
Set `COINTOS_VIEW_MODE=afk` on AFK launches; `driver` is the default. The coordinator
must choose from David's stated presence, not infer presence from display variables.
Headless launches retain the command for manual viewing. During driver mode,
unavailable viewing requires an explicit exception before dispatch.
Failure to open a window
does not interrupt work. No duplicate window is added to a run already in progress.
The native UI is interactive, NOT a read-only security boundary: viewing needs no
extra inference, but entering prompts or cancellation commands can affect the run.
Use normal UI quit/close to leave; do not use a task-cancellation command merely
to stop watching. Tested viewer-process termination leaves the server alive.

The listener is local to this machine, not a public/LAN service. Other local
processes can access it; this is not isolation from hostile local users. Do not
enable mDNS, sharing, remote binding or a persistent server as part of this feature.
Do not put inference bearer credentials in logs, view records or attach arguments.

Executor view records live under ignored `state/worker-views/`; commissioned MVP
dispatches use their ignored per-packet ledger. Records/logs remain for evidence
after completion; their recorded endpoint is no longer live once the run exits.
Never overwrite a prior view record, restart a worker because attachment failed,
or silently fall back to an invisible launch. Report an attachment/startup failure.

Installed OpenCode 1.18.29 advertises `run --port`, but its versioned run source
does not consume that option: a flag-only change is insufficient. This wrapper
uses the actual server/attach interfaces. Tests use a real OpenCode server and TUI
with providers disabled, plus an inert client for supervisor exit propagation;
they do not spend model tokens. The next admitted Qwen run remains the live
inference/close acceptance checkpoint. The existing non-attachable worker is
deliberately left alone.

Verification checkpoint: both focused real-process tests passed. The broad suite
was interrupted at David's request and is NOT claimed passing. David subsequently
approved finishing only the small wiring/review/commit remainder, with no broad
test rerun. Commissioned dispatch uses the same wrapper via bringup_bootstrap.py.

First live-view observation: David successfully viewed local-c1-publish-disposition
after selecting it via /sessions. Process inspection subsequently showed the manual
attach invocation ended in --session with no ID, explaining the initial home screen;
this was not evidence of an OpenCode session-navigation bug. Direct argv launch
removes that copy/paste failure. Automatic desktop opening awaits the next dispatch;
syntax checked only for this small hook, no additional broad test run.

Automatic desktop checkpoint: local-c1-publish-entry-reply launched its viewer
as a child of the existing GNOME Terminal server, with the complete session ID
ses_f8500f87effe90hWV24gHCaLlI. This is now the canonical local-agent spawn policy
in AGENTS.md, as David requested. This checkpoint is subject to the later driver/
AFK distinction above; it does not mandate spawning windows while David is AFK.

## Reusable monitor slots

Implemented by `scripts/worker_monitors.py`. Mutable, ignored bookkeeping lives in
`state/worker-monitors/registry.json`, protected by a file lock and atomic replacement;
this is not the append-only runtime evidence. Each slot tracks its monitor process,
worker server identity (PID/start time/boot), session, worktree and view record.

- A dedicated monitor process owns its terminal from inception, with a stable
  monitor-slot identity and explicit current worker/session association.
- It attaches to one live worker, retains a useful ended-state display after that
  worker closes, then attaches to the next assigned session in the same terminal.
  The ended display gives the run title and view-record path, not a full transcript.
- Concurrent active workers need distinct slots; do not replace a live worker's
  view or hijack unrelated terminals. View lifetime and inference lifetime remain
  separate. AFK launches neither create slots nor raise existing windows.
- Closing a monitor retires its slot without stopping its worker. Dead monitors
  are retired at the next assignment. Existing pre-pool windows are not adopted.
- No external focusing/centering or Wayland integration is attempted. Idle windows
  stay open for reuse; close them when unwanted. AFK launches do not populate them.
