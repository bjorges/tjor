## ADDED Requirements

### Requirement: Managed opencode configuration tier

A profile MAY provide `managed/opencode.json`. When staged, the cage SHALL
deploy it to opencode's managed-settings path (`/etc/opencode/opencode.json`)
owned by root and not writable, replaceable, or removable by the agent user —
so its settings load after, and cannot be overridden by, any user- or
project-level opencode configuration inside the cage. The deployment SHALL
happen before the harness starts. A staged `managed/opencode.json` that is
not valid JSON SHALL abort the launch before the harness starts (a session
must never look hardened without being it). When no profile stages a managed
file, any managed file left at that path from earlier activity SHALL be
removed, and behavior SHALL be identical to a session launched before this
capability existed. The `managed/` subdirectory SHALL NOT be copied into the
per-harness config overlay (it is not a harness definition directory), and
its staging SHALL pass through the same credential-filtering allow-list
pipeline as every other profile subdirectory.

#### Scenario: Managed settings are deployed agent-immutable

- **WHEN** a session is launched with a profile staging `managed/opencode.json`
- **THEN** `/etc/opencode/opencode.json` exists in the cage with that content,
  owned by root, and the agent user cannot write, replace, or remove it

#### Scenario: Invalid managed JSON refuses the launch

- **WHEN** the selected profile's `managed/opencode.json` is not valid JSON
- **THEN** the launch aborts with a clear error before the harness starts

#### Scenario: No managed file means no managed tier

- **WHEN** a session is launched with a profile that stages no
  `managed/opencode.json` (or with no profile at all)
- **THEN** `/etc/opencode/opencode.json` is absent in the cage, even if a
  previous launch had deployed one

#### Scenario: Managed file stays out of the harness config overlay

- **WHEN** a profile stages both `managed/opencode.json` and `agent/x.md`
- **THEN** the harness config dir receives `agent/x.md` but no `managed/`
  entry
