## MODIFIED Requirements

### Requirement: Named session derivation

When `--session <name>` is given (name matching `[A-Za-z0-9._-]{1,32}`), the session id SHALL be derived from both the workspace and the name; without it, derivation is unchanged (repo-scoped default session). Derivation SHALL be idempotent: a value already equal to, or prefixed by, the current workspace's qualified id SHALL resolve to the same session as its short form — never to a doubled id. A value that is an existing *other* workspace's fully-qualified session id SHALL be refused at launch with a clear error (launching this workspace under another workspace's session identity is never derived silently).

#### Scenario: Same repo, different names
- **WHEN** sessions `a` and `b` are launched from the same repo
- **THEN** their session ids differ and neither collides with the repo's default session

#### Scenario: Relaunching with the displayed qualified id
- **WHEN** `tjor run --session <qualified-id-of-this-workspace's-session>` is invoked (e.g. pasted from a tjor message)
- **THEN** it resolves to the same session as the short name — subject to the same already-running collision guard — and no doubled session id is ever created

#### Scenario: Foreign qualified id refused at launch
- **WHEN** `tjor run --session <id>` is given a fully-qualified id of an existing session belonging to a different workspace
- **THEN** the launch is refused with an error explaining the id belongs to another workspace
