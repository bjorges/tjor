# Spec Delta

## ADDED Requirements

### Requirement: Settings that create host mounts come from the user config only

The `[task]` table SHALL be read from the packaged defaults and the user config only. A `[task]` table in a repository config SHALL be ignored even when the file is trusted, with a warning naming the file and the table, because a value there would mount a host path the repository chose. An unknown key under `[task]` in the user config SHALL abort the launch, like an unknown key under `[landlock]` or `[broker]`, so a typo cannot silently switch the feature off.

#### Scenario: Repo config cannot set the notes directory
- **WHEN** a trusted `.tjor/config.toml` sets `task.notes_dir`
- **THEN** the value is ignored with a warning naming the file, and no notes directory is mounted unless the user config sets one

#### Scenario: Typo under the task table aborts
- **WHEN** the user config holds `[task]` with `note_dir = "..."`
- **THEN** the launch aborts naming the unknown key
