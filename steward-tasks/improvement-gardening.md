# Garden the improvement backlog

Review `.knowledge/what/is/current/technical_debt.md`,
`.knowledge/how/to/work/in/agent_ecosystem.md`, recent Auditor findings, and the
current implementation. Select one small item whose
repair reduces coupling or prevents a recurring failure. If the root cause is not
yet evidenced, queue an Auditor. If it is clear, queue a Refactorer with invariants,
acceptance checks, and non-goals. Avoid duplicate work, speculative frameworks, and
large rewrites. Check that no new OOP has entered the repository and advance the
existing class-based test migration when lower-risk priorities permit.
