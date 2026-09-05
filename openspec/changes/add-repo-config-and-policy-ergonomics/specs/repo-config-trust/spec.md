## Purpose

A repository may carry its own tjor config and egress policy so setups travel with the code — but because such config can widen the security boundary, it is honored only after the user explicitly approves it, pinned by content hash.

## ADDED Requirements

### Requirement: Repo config is honored only after approval

A repo `.tjor/config.toml` or `.tjor/policy.toml` SHALL be honored only if the user has approved its exact current content (tracked by content hash in a user trust store). An unapproved or since-changed repo config SHALL be ignored — falling back to the user/default config — with a loud warning naming the file and how to approve it.

#### Scenario: Untrusted repo config is ignored
- **WHEN** a repo has a `.tjor/policy.toml` that has not been approved
- **THEN** the launch uses the user/default policy, not the repo one, and warns that the repo policy is present but untrusted

#### Scenario: Approved repo config is honored
- **WHEN** the user has approved a repo `.tjor/config.toml` via `tjor trust`
- **THEN** its values layer over the user config for sessions in that repo

#### Scenario: Changed repo config requires re-approval
- **WHEN** an approved repo config file is subsequently edited
- **THEN** it is treated as untrusted again until re-approved

### Requirement: Trust approval and scaffolding commands

`tjor trust` SHALL display the repo's `.tjor` config/policy and record approval of its current content. `tjor trust --show` SHALL display without approving. `tjor init` SHALL scaffold a starter `.tjor/` (policy + config) in the current repo without approving it.

#### Scenario: Approve then honor
- **WHEN** the user runs `tjor trust` in a repo with a `.tjor` config
- **THEN** the content is approved and honored on the next launch, and the trust store records the approved hash

#### Scenario: Scaffold
- **WHEN** `tjor init` runs in a repo without a `.tjor/`
- **THEN** a starter `.tjor/policy.toml` and `.tjor/config.toml` are created and reported as present-but-untrusted
