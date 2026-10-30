# Spec Delta

## ADDED Requirements

### Requirement: An explicit workspace directory

`tjor run --workspace <dir>` SHALL launch as if invoked from `<dir>`: the workspace is resolved from that directory under every existing rule (version-control discovery with its cross-check, the sensitive-path gate, path fidelity), the harness starts in it, and the launch directory recorded for the session is that directory. A `<dir>` that does not exist or is not a directory SHALL refuse the launch.

#### Scenario: Launch from a task directory into a repository
- **WHEN** `tjor run --workspace ~/git/repo --task A` is invoked from `~/scratch/tasks/A`
- **THEN** the workspace is `~/git/repo` and the session id derives from it, exactly as a launch from inside it would

#### Scenario: Missing directory
- **WHEN** `--workspace` names a path that is not a directory
- **THEN** the launch is refused naming the path

## MODIFIED Requirements

### Requirement: Named session derivation

When `--session <name>` is given (name matching `[A-Za-z0-9._-]{1,32}`), the session id SHALL be derived from both the workspace and the name; without it, derivation is unchanged (repo-scoped default session). Derivation SHALL be idempotent: a value already equal to, or prefixed by, the current workspace's qualified id SHALL resolve to the same session as its short form — never to a doubled id. A value that is an existing *other* workspace's fully-qualified session id SHALL be refused at launch with a clear error (launching this workspace under another workspace's session identity is never derived silently). With `task.session_per_task` enabled and `--task <id>` given, the short name SHALL be `<session-or-harness>.<id>` lower-cased, built by the launcher and never re-parsed as a `--session` value; longer than 32 characters it SHALL be its first 23 characters, a dot and the first 8 hex characters of its hash; the launcher SHALL print the derived name.

#### Scenario: Same repo, different names
- **WHEN** sessions `a` and `b` are launched from the same repo
- **THEN** their session ids differ and neither collides with the repo's default session

#### Scenario: Relaunching with the displayed qualified id
- **WHEN** `tjor run --session <qualified-id-of-this-workspace's-session>` is invoked (e.g. pasted from a tjor message)
- **THEN** it resolves to the same session as the short name — subject to the same already-running collision guard — and no doubled session id is ever created

#### Scenario: Foreign qualified id refused at launch
- **WHEN** `tjor run --session <id>` is given a fully-qualified id of an existing session belonging to a different workspace
- **THEN** the launch is refused with an error explaining the id belongs to another workspace

#### Scenario: One session per task
- **WHEN** `task.session_per_task = true` and `tjor run --task A` then `tjor run --task B` are launched from one repository with the opencode harness
- **THEN** the sessions are `opencode.a` and `opencode.b`, distinct from each other and from the default session, and `--session rev --task A` yields `rev.a`

#### Scenario: A long composite name
- **WHEN** the composite `<session-or-harness>.<id>` exceeds 32 characters
- **THEN** the short name is its first 23 characters, a dot and 8 hex characters of its hash, the same on every launch

#### Scenario: Same task twice
- **WHEN** `tjor run --task A` is launched while the session for task A is running
- **THEN** the launch meets the existing running-session guard and names the session to attach to
