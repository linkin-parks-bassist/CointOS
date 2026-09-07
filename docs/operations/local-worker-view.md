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
On a graphical desktop the launcher now also requests a new GNOME Terminal window
automatically, passing the complete session ID as an argument. The viewer has no
inherited config descriptor and is detached from the worker's process group.
Headless launches retain the command for manual viewing; failure to open a window
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
