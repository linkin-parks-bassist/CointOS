---
status: green
revised_at: "2026-09-27T11:40:01+10:00"
---

David's direction of 2026-09-27, not yet built: **everything small, pipelined, hardware-like.** The local models (Qwen 27B and 4B) are slow, small and not very bright, so no agent should be given a large task. They do simple things; CointOS gets complicated things done through heavy use of abstraction, since an abstract concept is itself small and simple by design.

- **Break work down by concern, not by feature.** Not "JSON parser in C" into "parser + CLI + utils", but into a pipeline of atomic-ish stages with clear boundaries: tokenizer, lexer, parser, serializer and so on. Each item is hyper-manageable: one concern, one small interface.
- **Coherence by reverse feedback up the abstraction levels.** Small local pieces risk being locally sensible and globally incoherent. Reviewers of a piece report on its boundary: the interface it exposes and assumes, not its internals. Higher-level reviewers take those boundary reports and check coherence at the system level, each keeping its own concern small by working only at its level of abstraction.
- **Gardeners are small too.** A routine gardener picks 1–3 leaves at random, verifies their content against evidence and their consistency with the tree, fixes or reports, and ends. Separate broad-scale gardeners look across a tree for patterns of tree poisoning (log-shaped leaves, duplicated owners, stale narrative) and raise an alarm or act.

Observed evidence behind it (2026-09-27): the sandbox CLI worker spent 40 minutes and 13 tool calls without writing its change; the JSON-parser manager took over 50 minutes on one breakdown; the first routine gardening passes ran over 75 minutes each, and one wandered into the old installation at `~/.CointOS`. Four agents with 30k-token contexts share two lanes at about 9 tok/s, so every oversized task also starves the others.

Next: design with David how managers break work into pipelined stages, what a boundary report contains, how review levels are arranged, and how the gardener roles split (`what/is/next.md`).
