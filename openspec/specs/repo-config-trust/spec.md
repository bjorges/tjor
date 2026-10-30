# repo-config-trust Specification

## Purpose
A repository may carry its own tjor config and egress policy so setups travel with the code — but because such config can widen the security boundary, it is honored only after the user explicitly approves it, pinned by content hash.

## Requirements

### Requirement: Repo config is honored only after approval

A repo `.tjor/config.toml` or `.tjor/policy.toml` SHALL be honored only if the user has approved its exact current content (tracked by content hash in a user trust store). An unapproved or since-changed repo config SHALL be ignored — falling back to the user/default config — with a loud warning naming the file and how to approve it. Approval SHALL NOT extend to the user-only tables (below): their values in a repo config are ignored even when the file is trusted.

#### Scenario: Untrusted repo config is ignored
- **WHEN** a repo has a `.tjor/policy.toml` that has not been approved
- **THEN** the launch uses the user/default policy, not the repo one, and warns that the repo policy is present but untrusted

#### Scenario: Approved repo config is honored
- **WHEN** the user has approved a repo `.tjor/config.toml` via `tjor trust`
- **THEN** its values, except those of the user-only tables, layer over the user config for sessions in that repo

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

### Requirement: Settings that create host mounts come from the user config only

The `[task]` table SHALL be read from the packaged defaults and the user config layer only. A `[task]` table in a repository config SHALL be ignored even when the file is trusted, with a warning naming the file and the table, because a value there would mount a host path the repository chose. An unknown key under `[task]` in the user config SHALL abort the launch, like one under `[landlock]` or `[broker]`.

#### Scenario: Table typos and the user layer
- **WHEN** the user config holds a misspelled table `[tasks]`, or the operator's environment selects another user config file
- **THEN** the misspelled table only warns, as every table does, and the selected file is the user layer: the rule is about repository content, not the operator's environment

#### Scenario: Repo config cannot set the notes directory
- **WHEN** a trusted `.tjor/config.toml` sets `task.notes_dir`
- **THEN** the value is ignored with a warning naming the file, and no notes directory is mounted unless the user config sets one

#### Scenario: Typo under the task table aborts
- **WHEN** the user config holds `[task]` with `note_dir = "..."`
- **THEN** the launch aborts naming the unknown key
