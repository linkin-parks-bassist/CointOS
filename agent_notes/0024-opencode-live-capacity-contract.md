# OpenCode live-capacity mismatch — `/root`, 2026-09-10

Status: diagnosis complete; architecture approved by David; implementation and
activation not started.

## Durable finding

Plain interactive OpenCode and CointOS-managed workers currently have different
capacity paths. On 2026-09-10, `opencode` resolved first to
`/home/david/.local/bin/opencode`, a symlink directly to
`/home/david/.opencode/bin/opencode`. It therefore read
`/home/david/.config/opencode/opencode.json` without CointOS live-capacity
validation. That user file advertised Qwen3.8 as 131072 context / 43690 output.

The value was written and positively checked by Codex agent `/root` in session
`01a0862c-7cec-77f3-b7a3-d75586a5eb04` on 2026-09-09 while correcting the backend
from four fixed slots to one 131072-token slot. The check proved live context layout
but did not test OpenCode's output request ceiling. The 43690 output value appears
to be a generic one-third-of-context allowance; it was not established backend or
client capability evidence.

CointOS's separate `config/executor-opencode.json` advertises Qwen3.8 output 32768.
Earlier commissioning had already established that installed OpenCode clamps actual
output to 32000. None of these static values was reconciled at ordinary interactive
launch.

## Quill incident

Quill's last request ran from 23:05:44 AEST on 2026-09-09 to 00:05:57 on
2026-09-10. Lemonade recorded 3227 input and exactly 32000 output tokens over
3613 seconds, then returned HTTP 200. OpenCode 1.18.30 recorded total context 95444,
`finish: "length"`, and exited the loop. Kernel/system logs show no OOM kill,
thermal termination, or reboot. The stopped mid-sentence RTL was a client output
ceiling, not a backend context overflow or process crash.

This repeats the earlier structural failure: with `--ctx-size 131072 --parallel 4`,
OpenCode expected 131072 per request while fixed llama.cpp allocation supplied about
32768 per sequence. In both cases, OpenCode's compaction model used a larger declared
capacity than the serving boundary actually provided. The lower boundary terminated
first, so built-in compaction could not protect the run.

## Approved architectural decision

David chose live derivation with fail-closed validation:

- the serving backend's fresh effective per-request allocation is runtime authority;
- model training maximum, total pool, and static catalogues are not runtime truth;
- the installed OpenCode output ceiling is an exact version-qualified capability;
- every launch, including plain `opencode`, constructs one effective capacity record
  from those facts and emits an ephemeral config;
- unknown, stale, contradictory, or incompatible facts prevent inference;
- OpenCode compaction and CointOS continuation use the same effective denominator;
  and
- `finish: "length"` is incomplete execution even with HTTP 200 and exit zero.

Interactive admission policy may differ from managed-worker scheduling, but the two
paths may not differ about capacity truth. Persistent user configuration can own
plugins, MCP, names, and presentation; it must not independently own live capacity.

## Owning documents and next safe move

The approved design is
`docs/specs/2026-09-10-opencode-live-capacity-contract-design.md`.
The unexecuted plan is
`docs/plans/2026-09-10-opencode-live-capacity-contract.md`.

Implementation should begin with the pure effective-capacity record and tests. Do
not first edit the user JSON or replace the `opencode` symlink: that would conceal
the duplicated authority without building the validation boundary. Activation of
the interactive wrapper is a separate explicit David gate after full fake-endpoint
and read-only live-preflight evidence.

This note contains personal orchestration facts only. No Avnet task contents or
credentials are retained.
