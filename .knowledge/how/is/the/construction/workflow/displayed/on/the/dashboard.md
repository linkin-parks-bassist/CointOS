---
status: green
revised_at: "2026-10-29T08:15:16+11:00"
---

The project dashboard shows nine clickable construction stages: Decompose, Interfaces, Map tests, Review map, Write tests, Review tests, Implement, Review & integrate, Accepted. The workflow row shows current counts and running/held summaries. Clicking a stage opens its matching task list. The execution-status row beneath remains Blocked, Ready, Active, Review, Integrating and Landed.

workflowStage in web/dashboard.html resolves manager commands from an explicit Workflow stage: planning, test-mapping or map-review line in the assignment brief. Source and installed shared planning guidance requests this marker for future children. Existing recognisable map/review command names provide a presentation fallback. Other managers display Decompose. These markers label the logical manager stages; runtime construction-stage enums remain unchanged.

computeFlow joins both worker items and breakdown/manager tasks with queue records, so live manager execution is represented. Explicit task/queue holds classify as Blocked. workflowPosition places accepted work in Accepted and executable test packets awaiting/running integrator review in Review tests; implementation review belongs to Review & integrate.

The same stage classification appears in agent banners, Work rows, task-detail facts, project activity summaries and execution chips. Integrators reviewing test-contract workers get Review tests rather than generic integration. Accepted-artifact breakdowns distinguish test maps and map reviews from other planning.

Source and installed dashboard bytes agree and the live HTTP response was verified. Twenty-one focused dashboard/performance/Coin-visibility checks pass, including mapping-to-independent-review-to-authorship separation, live manager status, held classification, and executable-test review. A projection of the actual live ledger rendered all nine stages without changing any tasks.
