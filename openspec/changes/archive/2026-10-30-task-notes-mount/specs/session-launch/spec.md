# Spec Delta

## MODIFIED Requirements

### Requirement: Named session derivation

When `--session <name>` is given (name matching `[A-Za-z0-9._-]{1,32}`), the session id SHALL be derived from both the workspace and the name; without it, derivation is unchanged (repo-scoped default session). Derivation SHALL be idempotent: a value already equal to, or prefixed by, the current workspace's qualified id SHALL resolve to the same session as its short form — never to a doubled id. A value that is an existing *other* workspace's fully-qualified session id SHALL be refused at launch with a clear error (launching this workspace under another workspace's session identity is never derived silently). With `task.session_per_task` enabled, `--task <id>` given and no `--session`, the short name SHALL be the task id itself, set by the launcher without passing through the `--session` canonicalisation; an explicit `--session <name>` names the session as today. For that derived name the launch SHALL refuse an id equal to or prefixed by this workspace's base id, and a qualified-looking id that names an existing session (the lifecycle resolver's own lookup; an unreachable engine refuses rather than guesses).

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
- **WHEN** `task.session_per_task = true` and `tjor run --task a` then `tjor run --task b` are launched from one repository
- **THEN** the sessions are the repository's `a` and `b`, distinct from each other and from the default session, and `tjor down --session a` tears down the first

#### Scenario: Same task twice
- **WHEN** `tjor run --task a` is launched while the session for task `a` is running
- **THEN** the launch meets the existing running-session guard and names the session to attach to

#### Scenario: Session and task together
- **WHEN** `task.session_per_task = true` and `tjor run --session rev --task a` is invoked
- **THEN** the session is `rev`, the task label and notes directory are `a`, and a concurrent `tjor run --task a` with another harness gets the session `a`

#### Scenario: Two harnesses on one task without a session name
- **WHEN** `tjor run --harness claude --task a` runs and `tjor run --harness opencode --task a` is launched from the same repository
- **THEN** the second launch meets the running-session guard for session `a` and names `--session` as the way to run both

#### Scenario: Ids that would not round-trip are refused
- **WHEN** the workspace's base id is `repo-deadbeef` and `--task repo-deadbeef`, `--task repo-deadbeef-x`, or a task id equal to the full id of an existing session is given with `session_per_task`
- **THEN** the launch is refused explaining that `--session <id>` could not address the session

#### Scenario: Round trip
- **WHEN** `tjor run --task bug-12345678` launched the session and `tjor down --session bug-12345678` runs from the workspace
- **THEN** that session is torn down (with the resolver's notice that the value looked qualified), not the default session; a session with the full id `bug-12345678` created later makes the same command refuse as ambiguous rather than tear down either

### Requirement: Single config merge path

Every entry point SHALL obtain effective configuration through one shared merge implementation covering all config sections. When the current repo carries a `.tjor/config.toml` that the user has approved (`repo-config-trust`), it layers over the user config in that one merge path, except for the user-only tables, which the merge takes from the defaults and the user config alone; an unapproved repo config is excluded from the merge.

#### Scenario: Override honored everywhere
- **WHEN** a user override is set for any config section
- **THEN** every entry point (launcher, debug CLI, topology setup) observes the same effective value

#### Scenario: Trusted repo layer applies through the same path
- **WHEN** an approved repo `.tjor/config.toml` sets a value outside the user-only tables
- **THEN** every entry point observes it via the same merge path, layered over the user config

#### Scenario: User-only tables are skipped in the same path
- **WHEN** an approved repo `.tjor/config.toml` sets `task.notes_dir`
- **THEN** every entry point observes the user config's value, and the merge path reports the skipped table once
