# CointOS agent instructions

Follow the canonical knowledge-tree procedure once per fresh agent session. When
it is injected by the harness it is already loaded; otherwise load `knowledgetrees`
as the compatibility fallback. New question -> kt first; resolve lookup misses,
check eligible proofs and capture reusable answers before unrelated work or completion.
Respect current authority and permitted roots. Do not duplicate bootstrap work.

Knowledge trees remain standalone and are a core CointOS dependency. The canonical
runtime project tree lives at `~/.CointOS/.knowledge` and is registered as `cointos`.
The development checkout supplies installation knowledge; preserve runtime edits
and explicitly reconcile divergent leaves rather than overwriting them.
Runtime state/logs and installed executable assets live in `~/.CointOS`.
