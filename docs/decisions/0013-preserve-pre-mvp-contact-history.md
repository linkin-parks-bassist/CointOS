# 0013: Preserve pre-MVP contact history separately

Date: 2026-09-07. Status: direction approved by David; conversion implementation
and live cutover are not yet accepted.

## Context

Pre-MVP turns recorded front/deep processing, not necessarily an explicit
respond/dispatch decision. Fabricating a canonical decision, delivery observation,
or job identity during conversion would misrepresent historical evidence.
The C1 plan requires terminal-history conversion and refusal of active legacy work.

## Decision

David approved preserving finished pre-MVP records unchanged in a separate
immutable historical archive, with a durable replay fence for their inbound IDs.
New active processing uses only the canonical format. Historical envelopes mixed
into the active turn store were considered but would require ongoing historical
branching in active consumers; they are not the chosen direction.

The conversion design must preserve original record bytes and bind each replay
fence to the preserved evidence. Repeated historical updates must not enqueue a
task, invoke a fresh decision, or send a reply. Archive and fence durability must
be established before retiring an old active-store entry; interrupted conversion
must remain safely resumable without overwrite or invented success.

Only genuinely terminal legacy turns qualify. Nonterminal, malformed, conflicting
or uncertain records remain explicit preview blockers, not silently archived as
complete. Runtime JSONL remains append-only and is never rewritten by conversion.
The old inbox egress field represented the degraded notice: its historical value
must not be reinterpreted as a canonical substantive-decision acknowledgement.

## Consequences and remaining acceptance

The precise archive/index format, converter interface, caller replay behavior and
offline crash/replay tests must be specified together before implementation.
This direction refines C1/C4; it does not authorize deployment, service changes,
live record migration, or bypassing the offline composition and rollback gate.
Keep the archived original evidence inspectable after cutover. No conversion has
been performed at this checkpoint.

See [contact work and evidence](../../agent_notes/0018-canonical-contact.md) and
the [approved contact plan](../plans/2026-09-05-cointos-mvp-contact.md).
