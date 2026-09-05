## Purpose

Sessions as first-class objects: enumerate them, reattach to them, run several per repo, and clean up after them — without ad-hoc docker commands and without ever silently destroying session state.

## ADDED Requirements

### Requirement: Sessions are discoverable

`tjor ls` SHALL list every tjor session on the machine — session id, workspace, running/exited state, agent count, task id (when set), and age — derived from container labels, never from parsing container names.

#### Scenario: Two sessions, one running
- **WHEN** one session has a live agent and another's containers have exited
- **THEN** `tjor ls` shows both, correctly distinguishing their states

### Requirement: Listing re-verifies core guarantees

For every session with running containers, `tjor ls` SHALL re-check that the session's agent network is still internal-only and SHALL flag any degraded session loudly.

#### Scenario: Tampered network detected after launch
- **WHEN** a session's internal network no longer reports internal-only
- **THEN** `tjor ls` marks that session DEGRADED with an explicit warning

### Requirement: Reattachment

`tjor attach [session]` SHALL reattach the terminal to a running agent container. With no argument and exactly one running session, it attaches to it; with several candidates it SHALL offer an interactive picker; with none it SHALL say so and exit non-zero.

#### Scenario: Reattach after a dropped terminal
- **WHEN** an agent container is running and `tjor attach` is invoked with its session id
- **THEN** the terminal is attached to that agent's TTY

### Requirement: Multiple sessions per repo

`tjor run --session <name>` SHALL derive a distinct session id from the workspace AND the name, giving the session its own topology, state root, and identity. Concurrent named sessions in one repo SHALL NOT share containers, networks, credentials directories, or identity values (charter L29).

#### Scenario: Parallel sessions in one repo
- **WHEN** `tjor run --session a` and `tjor run --session b` run concurrently in the same repo
- **THEN** each has its own proxy, DNS, network, state root, and `TJOR_SESSION_ID`

### Requirement: Garbage collection is safe by construction

`tjor gc` SHALL remove exited tjor agent containers, tear down topologies (sidecars, networks, volumes) that have had no running agent for longer than the age threshold (default 24h, `--age` to override), and support `--dry-run` listing exactly what would be removed. `gc` SHALL NEVER delete session state directories, and SHALL only ever delete docker resources carrying tjor session labels.

#### Scenario: Dry run first
- **WHEN** `tjor gc --dry-run` runs on a machine with reapable sessions
- **THEN** every candidate is listed and nothing is removed

#### Scenario: State survives collection
- **WHEN** `tjor gc` tears down an idle session's topology
- **THEN** the session's state directory (auth, history) is intact and a later `tjor run` in that repo resumes from it

### Requirement: Tiered state reset

`tjor reset {cache|sessions|creds|all}` SHALL delete only the corresponding tier of the current repo's session state (harness caches; harness session/history data; credential material including the session CA; everything), SHALL support `--dry-run`, and SHALL require the tier argument — there is no default tier.

#### Scenario: Wiping caches keeps auth
- **WHEN** `tjor reset cache` runs
- **THEN** harness cache directories are gone and credentials/auth survive

#### Scenario: Dry run lists paths
- **WHEN** `tjor reset all --dry-run` runs
- **THEN** every path that would be deleted is printed and nothing is deleted
