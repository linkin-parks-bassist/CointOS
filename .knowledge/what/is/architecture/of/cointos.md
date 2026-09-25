---
status: green
revised_at: "2026-09-15T11:58:21+10:00"
---

CointOS represents work as versioned filesystem records and append-only events.
Intake and contact produce durable turns or jobs; preparation combines the task,
role, policy, and bounded context; routing and resource owners choose an executable
model allocation; OpenCode performs tool work; independent evidence determines
acceptance; dependent outbox records carry results back to contact surfaces.

Keep domain policy separate from adapters. Telegram owns transport, Lemonade owns
model serving, OpenCode owns the tool-running client, systemd owns process
supervision, and filesystem modules own persistence. None of those adapters defines
agent identity, semantic completion, authority, or context capacity. Source/runtime
locations and concrete entry points are in `where/is/code/for/cointos.md`; establish
live state through `where/is/runtime_truth.md`.

Knowledge trees are a standalone system and a core CointOS dependency. CointOS integrates permitted roots, canonical procedures and task-lifecycle obligations without absorbing or duplicating KT ownership. Integration proposals and the outstanding launch/resume audit are in `how/should/standalone/knowledge/trees/integrate/with/cointos.md`. Development source and installed execution are distinct; the intended installer deploys required code/config/prompts to `~/.CointOS` while preserving runtime records.

CointOS working-model vision (David,2026-09-15): broad ideas enter a dissolution pipeline. A swarm of chunkers progressively breaks concepts and concerns into smaller tasks, one decomposition step at a time, until pieces are small and concrete enough for local models to execute quickly. Small concrete tasks may include abstract architectural reasoning: abstraction aims to make concerns smaller, not exclude thought from local models. Do not give one local model an entire complex integration problem.

Stages review outputs at appropriate thought/abstraction levels. Abstraction barriers constrain each task’s conceptual context; children receive the bounded context necessary for their piece, and parent stages integrate their results. The GPU scheduler serves this diffuse stochastic flow of decomposition, execution and review actions. Cointelprofessional poses questions, obtains feedback and returns it to the pipeline. This is the intended mechanism for turning ideas into reality, not a claim that the current fixed-role runtime already implements it. Concrete stages, contracts and stochastic scheduling policy remain to be designed.

A dissolved child task should normally receive a fresh bounded execution session containing only its task contract and necessary parent result. Retained session identity is for continuity after suspension or for a genuinely dependent next step; it is not the default for unrelated chunks. Reusing a long retained OpenCode session for the independent park-function edit caused the local model to prefill tens of thousands of prior tokens before doing a small task, an observed scheduling tax that defeats ensmallening even though GPU dispatch succeeded. Future chunk dispatch must choose continuity deliberately and otherwise begin fresh.
