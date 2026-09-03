# 0004: Permit scoped package installation

Status: accepted, 2026-09-03.

## Context

Agents encounter ordinary missing build dependencies. Requiring David to reproduce
every installation wastes attention, while unrestricted sudo would turn generated
shell into an unbounded root interface.

## Decision

Workers and Refactorers may install precisely named packages from already configured
APT repositories through a root-owned validating wrapper. It rejects options, paths,
package files, unknown repository entries, and empty requests. Sudo authorizes only
that wrapper. Direct apt, sudo, repository changes, removals, upgrades, services,
and arbitrary privileged commands remain blocked. Installs enter the system journal
and ordinary agent evidence.

Changing the root-owned wrapper or policy requires explicit authorization.

## Consequences

Repository packages may run trusted-distribution maintainer scripts as root; this
is inherent to APT. The boundary trusts configured Ubuntu repositories, not arbitrary
downloads. Install only task-relevant dependencies, never speculative decoration.
