# Spec Delta

## ADDED Requirements

### Requirement: State root inventory

`tjor ls --state` SHALL list every session state directory under the configured session root, one row each: session id, workspace (unknown without metadata), last activity, whether any container of that session is running, and which credential paths are present. Last activity SHALL be derived from file timestamps without following symbolic links. An entry under the session root that is not a real directory SHALL be reported and never descended.

#### Scenario: Legacy and current directories side by side
- **WHEN** the session root holds a directory written by an earlier version and one with metadata
- **THEN** both are listed; the legacy row shows its workspace as unknown and its last activity from file timestamps, the other shows its recorded workspace

#### Scenario: Credential presence is flagged
- **WHEN** a state directory holds a broker file and a harness auth file
- **THEN** its row names both credential paths; a directory holding neither shows none

#### Scenario: A planted symlink is reported, not followed
- **WHEN** an entry under the session root is a symbolic link to a directory elsewhere
- **THEN** the listing reports the entry as not a directory and no path behind the link is read or counted

### Requirement: Prune is explicit and dry-runnable

`tjor prune` SHALL delete session state only for sessions selected by `--older-than <duration>` (last activity before the cutoff) and/or one or more `--session <name|id>`, SHALL refuse with usage when no selector is given, and SHALL support `--dry-run`, which lists exactly what a real run would remove and removes nothing. No other command SHALL invoke prune; `tjor gc` SHALL continue never to delete state.

#### Scenario: No selector, no deletion
- **WHEN** `tjor prune` runs without `--older-than` or `--session`
- **THEN** it exits non-zero with usage and nothing is removed

#### Scenario: Dry run first
- **WHEN** `tjor prune --older-than 30d --dry-run` runs with matching idle sessions
- **THEN** every state directory that a real run would remove is listed with its age and credential flags, and all of them still exist afterwards

#### Scenario: Age selection
- **WHEN** `tjor prune --older-than 30d` runs with one directory last active 40 days ago and one 2 days ago
- **THEN** only the older directory is removed and the command names it

### Requirement: Prune refuses state that is in use or unreviewed

`tjor prune` SHALL refuse a session with any running container, agent or sidecar, directing the operator to `tjor down`; this refusal has no override. It SHALL refuse a session whose git-check marker is pending unless `--force` is given, because the state directory holds the baseline of unreviewed cage-written git metadata. When the container runtime cannot be queried, prune SHALL refuse rather than assume nothing is running.

#### Scenario: Running agent refused
- **WHEN** `tjor prune --session a` names a session with a running agent
- **THEN** the session is refused with a message naming `tjor down`, and its state directory is untouched

#### Scenario: Sidecars only still count as in use
- **WHEN** a session's agent has exited but its proxy or DNS sidecar is still running
- **THEN** prune refuses it the same way

#### Scenario: Pending git-check marker refused
- **WHEN** a selected session's git-check marker is pending
- **THEN** prune refuses it, names `tjor git-check --session <id>` as the way to review, and removes nothing for that session

#### Scenario: Force overrides only the marker
- **WHEN** `tjor prune --session a --force` names a session with a pending marker and no running container
- **THEN** the directory is removed; `--force` does not override the running-container refusal

### Requirement: Prune deletes through the symlink guard

Every path prune removes SHALL have only real directories between the session root and the path's parent; a symbolic link or non-directory anywhere in that prefix SHALL refuse that path loudly and prune SHALL continue with the rest. `--creds-only` SHALL remove only the credential tier of each selected session and leave harness history, caches and metadata in place.

#### Scenario: Planted symlink ancestor refused
- **WHEN** an intermediate directory inside a selected state directory has been replaced by a symbolic link to a location outside the session root, and `--creds-only` targets a path beneath it
- **THEN** that path is refused with a loud message, nothing behind the link is deleted, and the other selected paths are still processed

#### Scenario: Whole directory removed
- **WHEN** `tjor prune --session a` selects an idle session with no pending marker
- **THEN** the entire state directory is removed and no other session's directory is touched

#### Scenario: Credentials only
- **WHEN** `tjor prune --session a --creds-only` runs
- **THEN** the session's credential paths are removed and its harness history, caches and metadata remain

### Requirement: The credential tier is one set

The credential paths that `tjor ls --state` flags, that `tjor prune --creds-only` removes and that `tjor reset creds` removes SHALL be the same set, defined once, so a credential location added for one command is covered by all three.

#### Scenario: One definition
- **WHEN** a state directory holds every path of the credential tier
- **THEN** `tjor ls --state` flags each of them, and after `tjor prune --session <id> --creds-only` none of them remain while the non-credential tiers do
