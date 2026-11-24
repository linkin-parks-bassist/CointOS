---
status: green
revised_at: "2026-11-25T10:47:16+11:00"
---

The requested direction is to extract CointOS's inference scheduling into a standalone system that can accept an OpenAI-compatible backend endpoint, including Lemonade, maintain multiple ongoing sessions and schedule their model work. It must also accommodate hosted model requests, where the upstream provider executes inference and the local service submits requests and streams their results. This is an architecture exploration; the project name, repository, public contract and extraction plan are not yet settled.

The current implementation separates a pure scheduling decision in cointos/scheduler.py from execution in lanes.py. lanes.py depends on daemon state, memory/capacity admission, snapshots and backend operations. Native preemption occurs between bounded prefill/generation steps. Backends expose additional operations for token-state validation, resident selection and persistence. Extracting scheduler.py alone does not provide a working standalone inference service.

OpenAI-compatible request transport and native execution control are distinct capabilities. Conversation continuity can be represented by durable messages/tool records; GPU KV/resident state is a backend-specific performance representation. The existing backend contract demonstrates why pause/resume cannot be assumed from a chat-completions URL. A generic endpoint needs a full-request execution path unless its adapter exposes stronger execution controls.

The unresolved scope is whether the new service owns conversation histories, agent processes/tool execution, or inference scheduling and request lifetimes only. The design recommendation under discussion is a common request/session service with ordinary HTTP execution and optional native step-control capabilities, while agent runtimes retain tools and process lifecycle. This recommendation is not an approved implementation contract. Preserve the live CointOS deployment while settling these boundaries.
