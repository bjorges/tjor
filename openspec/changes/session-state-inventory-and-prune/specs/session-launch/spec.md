# Spec Delta

## ADDED Requirements

### Requirement: Launch records session metadata

Every launch SHALL write a metadata file into the session's state root recording the workspace path, harness, profile (name or directory, or none), task id, the first and the most recent launch time, and the launch count. The write SHALL be atomic (a crash never leaves a torn file) and the file SHALL contain no credential or token. A state root created by an earlier version, with no metadata file, SHALL read as unknown metadata — never as an error.

#### Scenario: First launch creates the metadata
- **WHEN** a session is launched for the first time
- **THEN** its state root holds a metadata file naming the workspace, harness, profile, task id, a first-launch time equal to the last-launch time, and a launch count of 1

#### Scenario: Relaunch updates, never resets, the metadata
- **WHEN** the same session is launched again, with a different task id
- **THEN** the metadata keeps the first-launch time, updates the last-launch time and the task id, and increments the launch count

#### Scenario: Legacy state root
- **WHEN** a state root from an earlier version has no metadata file
- **THEN** lifecycle commands treat its workspace, harness and launch times as unknown and proceed

#### Scenario: Metadata holds no secret
- **WHEN** a session is launched with a broker and an agent profile configured
- **THEN** the metadata file contains no credential, token, key or CA material — only the fields named above
