---
status: green
revised_at: "2026-09-14T22:54:59+10:00"
---

Knowledge trees remain independently usable and maintained, while serving as a core CointOS component. CointOS should integrate their public procedures and interfaces rather than absorb their implementation or fork a competing memory system. This ownership boundary is David's requirement; the exact integration design is still open.

Initial design proposal: CointOS owns task/session lifecycle, active permitted root selection, launch-time provision of canonical KT instructions, and durable association of knowledge obligations with jobs. Standalone KT owns semantic lookup/capture/amend/prove behavior, leaf format and proof semantics. Agent entry and recovery paths should consistently supply the same root/procedure contract; task preparation should point to governing leaves and bounded checked facts. Runtime task records and append-only operational evidence remain separate from semantic knowledge, with truthful source links when reusable conclusions are captured.

Next action is a narrow integration audit during restoration: identify every actual agent launch/resume path, what KT instructions and roots it receives, and which lookup/capture/proof obligations are enforced versus merely reminded. Record gaps before choosing an adapter or lifecycle-hook design. Do not require a large integration rewrite before useful parallelism/control-plane restoration. Avoid duplicate bootstrap injection and keep scope/access policy authoritative. Tests should exercise actual launch/recovery boundaries and standalone use independently. The lifecycle adapter, failure semantics and enforcement design are proposals pending that audit; no implementation completeness is claimed.
