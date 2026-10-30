## MODIFIED Requirements

### Requirement: Settings that create host mounts come from the user config only

The user-only tables are `[task]`, whose values mount a host path the repository would choose (ADR 0013), and `[harness]`, whose values shape the harness's command line (ADR 0014). Both SHALL be read from the defaults and the user config only; either table in a trusted repository config SHALL be ignored with a warning naming the file and the table; an untrusted file is ignored whole, as today. An unknown key under either, nested `[harness.<name>]` included, SHALL abort the launch.

#### Scenario: Table typos and the user layer
- **WHEN** the user config holds a misspelled table `[tasks]`, or the operator's environment selects another user config file
- **THEN** the misspelled table only warns, as every table does, and the selected file is the user layer: the rule is about repository content, not the operator's environment

#### Scenario: Repo config cannot set the notes directory
- **WHEN** a trusted `.tjor/config.toml` sets `task.notes_dir`
- **THEN** the value is ignored with a warning naming the file, and no notes directory is mounted unless the user config sets one

#### Scenario: Typo under the task table aborts
- **WHEN** the user config holds `[task]` with `note_dir = "..."`
- **THEN** the launch aborts naming the unknown key

#### Scenario: Repo config cannot set harness arguments
- **WHEN** a trusted `.tjor/config.toml` sets `[harness.opencode] args = ["--auto"]`
- **THEN** the table is ignored with a warning naming the file and `[harness]`, the launch uses the user config's arguments or none, and the configuration check reports the same

#### Scenario: Unapproved file with a harness table
- **WHEN** an unapproved `.tjor/config.toml` holds `[harness.claude] args`
- **THEN** the whole file is ignored with the untrusted warning, as for any unapproved file; no table-specific warning is owed

#### Scenario: Typo under a harness table aborts
- **WHEN** the user config holds `[harness.claude]` with `arg = ["--model", "opus"]`, or a nested table `[harness.cluade]`
- **THEN** the launch aborts naming the unknown key, `harness.claude.arg` or `harness.cluade`
