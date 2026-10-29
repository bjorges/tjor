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

### Requirement: Lifecycle commands create no session state

Resolving a session name or id for any command other than `tjor run` SHALL NOT create, modify or touch anything under the session root. Only a launch creates a session's state directory, and only after every launch refusal has passed.

#### Scenario: A mistyped session name leaves nothing behind
- **WHEN** `tjor prune --session typo --dry-run`, `tjor down --session typo` or `tjor reset cache --session typo` names a session that has no state directory
- **THEN** no directory for it exists afterwards and the command reports that it found nothing to act on

#### Scenario: Reading does not refresh a directory
- **WHEN** `tjor ls --state` or `tjor prune --older-than 30d --dry-run` runs over an idle state directory
- **THEN** the directory's last activity is the same before and after

### Requirement: A launch holds the session lock while it writes state

From its first write into the session's state directory until the agent container exists, a launch SHALL hold a per-session lock stored outside the state directory. A launch that finds the lock held by a live process SHALL refuse, naming the lock and its holder, before writing into the state root or minting a credential. A lock left by a process that no longer exists SHALL be cleared with a message. The lock SHALL be released on every exit path of the launch.

#### Scenario: Launch refused while the session is being pruned
- **WHEN** `tjor prune --session a` holds the lock of session `a` and `tjor run --session a` starts
- **THEN** the launch exits non-zero naming the lock and its holder, writes nothing into the state root, and mints no credential

#### Scenario: A stale lock does not block a launch
- **WHEN** the lock of session `a` names a process that no longer exists
- **THEN** `tjor run --session a` clears it, says so, and proceeds

#### Scenario: A second launch of the same session is refused during the first one's setup
- **WHEN** a launch of session `a` has taken the lock but not yet created its agent container, and a second `tjor run --session a` starts
- **THEN** the second launch is refused naming the lock, instead of sharing the first one's credentials and topology

#### Scenario: A refused launch releases the lock
- **WHEN** a launch takes the lock and is then refused (a sensitive `--dir`, a missing image)
- **THEN** the lock is released and the next launch of that session is not refused for it
