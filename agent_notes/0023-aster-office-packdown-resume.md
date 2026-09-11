# Office pack-down: existing Qwen sessions

Recorded by Aster (Astra), 2026-09-09, at David's request. Do not request
model-written handoffs or start replacement workers during morning pack-down.
Preserve existing worktrees, OpenCode session storage and append-only JSONL.

These exact identities were read from the per-run view records. Record all eight
original runs, not merely the currently visible windows; completion and live
process state must be checked separately before resuming any one of them.

| Packet | OpenCode session | Worktree under `/home/david/.worktrees/` |
| --- | --- | --- |
| local-terminal-error-exit-fix | ses_f8097503fffe9ym9C3NCe6bfIa | cointos-next-terminal-error |
| local-parent-lock-fix | ses_f80974f85ffeeaI3m8zayaNg74 | cointos-next-parent-lock |
| local-handler-count-fix | ses_f80974f2bffeLuqHN3tJ6aPLqp | cointos-next-handler-count |
| local-timeout-persistence | ses_f80974eebffeKb9XVGfTzHzBt0 | cointos-next-timeout-persistence |
| local-executor-fixture-fix | ses_f80974e9dffekyXOQQfPJqwoTj | cointos-next-executor-fixture |
| local-p1-binding-impl | ses_f80974e3effeiaetwwfOj9Gile | cointos-next-p1-binding |
| local-h1-definition-impl | ses_f80974dc1ffehr0T1cOCMNyRxY | cointos-next-h1-definition |
| local-contact-projection-review2 | ses_f80974d56ffeJG07CyE1JOdiuc | cointos-next-contact-review |

Original prompts, logs and view records are in the ignored ledger
`/home/david/.CointOS/development/sdd/2026-09-05-cointos-mvp-index/`, named after each packet.
Contact review has a final report already audited in note 0022: do not rerun it.

Resume through the canonical admitted observable launcher, supplying the exact
existing `--session` ID and worktree. The observable wrapper already accepts an
explicit session; the commissioning bootstrap currently does not expose a resume
argument, so do not simply rerun its original dispatch or bypass admission with
a naked inference command. Read current job/lease state and verify old owners
absent before creating a new admitted runner. Use 1–3 genuinely independent jobs.
Old loopback attach URLs are ephemeral and will not survive reboot.

The installed CLI supports `opencode export SESSION_ID --pure` for JSON session
export and `opencode run --session SESSION_ID` for continuation. Continuation is
saved conversation/tool history plus filesystem state, not a saved KV cache or
an exact continuation of an interrupted tool/process. Inspect partial edits and
unfinished tool effects before continuing. No shutdown or cancellation was
performed as part of recording these identities.

A read-only export check for the terminal-error session produced truncated JSON
when piped to jq (unfinished string), so no validated export backup or end-to-end
resume proof is claimed. Preserve the original OpenCode session database and
runtime logs; investigate export separately if needed.

Concurrency observation before pack-down: live Qwen llama-server has `--parallel 8`
and a shared 262144-token pool; `/slots` showed four processing slots. The proxy
source/config still limits request handlers to four. Multiple OpenCode sessions
can remain mid-task while waiting upstream. The commissioning path waits for the
runner process; it does not perform periodic context checkpoint/eject/restore.
Closing an attached oversight viewer does not stop its admitted worker by design.

## Authorized stop completed

David then explicitly requested worker shutdown. Aster verified each bound PID's
start ticks, process group and exact wrapper/view-record command before signalling.
The terminal-error, parent-lock, handler-count, timeout-persistence and executor-
fixture supervisors received SIGTERM after proxy cancellation was requested.
P1, H1 and contact-review owners were already absent. All eight process groups
were subsequently absent and all eight backend slots idle. Existing ownership
functions revoked all eight proxy credentials and released their inference and
worker occupancy; durable audit events record this without invented exit codes.

Job records are conservatively marked failed with explicit pack-down/unknown-exit
reasons and operator_packdown metadata, preventing accidental automatic continuation.
This is not a semantic rejection of completed reports: review final P1/H1 packets
and retain the already-reviewed contact report. Actual OS exit codes were not
available to this operator; they were not fabricated. No model-written handoffs,
model unloads, service stops or workstation shutdown were performed. Partial edits
remain in terminal-error, handler-count and executor-fixture worktrees; inspect
all worktrees afresh before resuming. Session IDs above remain the resume map.
