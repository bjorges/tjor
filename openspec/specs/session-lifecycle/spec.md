# session-lifecycle Specification

## Purpose
Sessions as first-class objects: enumerate them, reattach to them, run several per repo, and clean up after them — without ad-hoc docker commands and without ever silently destroying session state.

## Requirements

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

`tjor attach [session]` SHALL reattach the terminal to a running agent container, accepting either the fully-qualified session id or the short session name (resolved against the current workspace). With no argument and exactly one running session, it attaches to it; with several candidates it SHALL offer an interactive picker; with none it SHALL say so and exit non-zero.

#### Scenario: Reattach after a dropped terminal
- **WHEN** an agent container is running and `tjor attach` is invoked with its session id
- **THEN** the terminal is attached to that agent's TTY

#### Scenario: Reattach by short name
- **WHEN** a named session is running and `tjor attach <short-name>` is invoked from its workspace
- **THEN** the short name resolves to the same session as its fully-qualified id and the attach proceeds

### Requirement: Session references resolve unambiguously

Lifecycle commands taking `--session` (`down`, `status`, `denials`, `reset`) SHALL accept both the short session name and the fully-qualified session id, resolving them to the same session. Resolution SHALL be idempotent: a value already carrying the current workspace's qualification prefix SHALL never be qualified again (no doubled ids, ever). A fully-qualified id belonging to another workspace SHALL be honored verbatim when a session with that exact id exists (state directory or labeled containers), making lifecycle commands usable from any working directory; the resolution SHALL state that a fully-qualified id is being used. A value that merely looks like a fully-qualified id but matches no existing session SHALL be treated as a short name, with a notice. Error and hint messages that display a session reference alongside a command SHALL only show invocations that are safe to paste verbatim.

#### Scenario: Pasting the displayed qualified id tears down the right session
- **WHEN** `tjor down --session <qualified-id>` is run with the exact id tjor's own messages displayed, from the launch workspace
- **THEN** that session — not a doubled phantom — is torn down

#### Scenario: Teardown from a different working directory
- **WHEN** `tjor down --session <qualified-id>` is run from a directory other than the session's workspace and a session with that id exists
- **THEN** the named session is torn down, with a notice that a fully-qualified id was used

#### Scenario: Qualified-looking short name still works
- **WHEN** `--session` receives a value shaped like a qualified id but no session with that exact id exists
- **THEN** the value is treated as a short name (with a notice) and resolution proceeds as for any short name

#### Scenario: Teardown that matches nothing says so
- **WHEN** `tjor down` resolves to a session with no containers and no state directory
- **THEN** the command reports that nothing was found for that session instead of silently reporting success

### Requirement: Multiple sessions per repo

`tjor run --session <name>` SHALL derive a distinct session id from the workspace AND the name, giving the session its own topology, state root, and identity. Concurrent named sessions in one repo SHALL NOT share containers, networks, credentials directories, or identity values (charter L29).

#### Scenario: Parallel sessions in one repo
- **WHEN** `tjor run --session a` and `tjor run --session b` run concurrently in the same repo
- **THEN** each has its own proxy, DNS, network, state root, and `TJOR_SESSION_ID`

### Requirement: Garbage collection is safe by construction

`tjor gc` SHALL remove exited tjor agent containers, tear down topologies (sidecars, networks, volumes) that have had no running agent for longer than the age threshold (default 24h, `--age` to override), and support `--dry-run` listing exactly what would be removed. `gc` SHALL NEVER delete session state directories, and SHALL only ever delete docker resources carrying tjor session labels. When a broker credential exists for a session being torn down, `gc` SHALL revoke it (the D2 credential-broker hook) before removing the session's resources.

#### Scenario: Dry run first
- **WHEN** `tjor gc --dry-run` runs on a machine with reapable sessions
- **THEN** every candidate is listed and nothing is removed

#### Scenario: State survives collection
- **WHEN** `tjor gc` tears down an idle session's topology
- **THEN** the session's state directory (auth, history) is intact and a later `tjor run` in that repo resumes from it

#### Scenario: Brokered credential revoked on teardown
- **WHEN** `tjor gc` (or `tjor down`) tears down a session that holds a brokered credential
- **THEN** that credential is revoked before the session's resources are removed

### Requirement: Tiered state reset

`tjor reset {cache|sessions|creds|all}` SHALL delete only the corresponding tier of the current repo's session state (harness caches; harness session/history data; credential material including the session CA; everything), SHALL support `--dry-run`, and SHALL require the tier argument — there is no default tier.

#### Scenario: Wiping caches keeps auth
- **WHEN** `tjor reset cache` runs
- **THEN** harness cache directories are gone and credentials/auth survive

#### Scenario: Dry run lists paths
- **WHEN** `tjor reset all --dry-run` runs
- **THEN** every path that would be deleted is printed and nothing is deleted

### Requirement: State root inventory

`tjor ls --state` SHALL list every session state directory under the session root: session id, workspace, last activity, container state and credentials present. Last activity SHALL be the newest timestamp over the whole directory, never following symbolic links, floored by the recorded last launch; a directory that cannot be fully read SHALL report unknown, never old. An entry that is not a real directory SHALL be reported, never descended. The inventory SHALL require the container daemon.

#### Scenario: Legacy and current directories side by side
- **WHEN** the session root holds a directory written by an earlier version and one with metadata
- **THEN** both are listed; the legacy row shows its workspace as unknown and its last activity from file timestamps, the other shows its recorded workspace

#### Scenario: Activity deep in the harness history counts
- **WHEN** a state directory's newest file is a harness history entry many levels below the directory, and nothing nearer the top has changed since
- **THEN** the row's last activity is that file's time

#### Scenario: Unreadable state is unknown, not stale
- **WHEN** a subdirectory of a state directory cannot be read
- **THEN** the row's last activity shows unknown, and `tjor prune --older-than` never selects that session by age

#### Scenario: Credential presence is flagged
- **WHEN** a state directory holds a broker file and a harness auth file
- **THEN** its row names both credential paths; a directory holding neither shows none

#### Scenario: Container state is shown, never guessed
- **WHEN** one session has a running agent, one only an exited container, and one no container at all
- **THEN** their rows show running, stopped and none; when the daemon cannot be queried the command fails instead of printing a guess

#### Scenario: A planted symlink is reported, not followed
- **WHEN** an entry under the session root is a symbolic link to a directory elsewhere
- **THEN** the listing reports the entry as not a directory and no path behind the link is read or counted

### Requirement: Prune is explicit and dry-runnable

`tjor prune` SHALL delete session state only for sessions chosen by exactly one selector: `--older-than <duration>` (last activity before the cutoff; unknown activity is never selected) or one or more `--session <name|id>`. Both selectors, or neither, SHALL be refused with usage, exit non-zero and remove nothing. `--dry-run` SHALL list exactly what a real run would remove and remove nothing. No other command SHALL invoke prune; `tjor gc` SHALL continue never to delete state.

#### Scenario: No selector, no deletion
- **WHEN** `tjor prune` runs without `--older-than` or `--session`
- **THEN** it exits non-zero with usage and nothing is removed

#### Scenario: Both selectors are refused
- **WHEN** `tjor prune --session a --older-than 30d` runs
- **THEN** it exits non-zero with usage and nothing is removed — neither session `a` nor any old session

#### Scenario: Dry run first
- **WHEN** `tjor prune --older-than 30d --dry-run` runs with matching idle sessions
- **THEN** every state directory that a real run would remove is listed with its age and credential flags, and all of them still exist afterwards

#### Scenario: Age selection
- **WHEN** `tjor prune --older-than 30d` runs with one directory last active 40 days ago and one 2 days ago
- **THEN** only the older directory is removed and the command names it

### Requirement: Prune refuses state that is in use or being launched

`tjor prune` SHALL refuse a session that has any container, in any state and of any role, directing the operator to `tjor down`; this refusal has no override. It SHALL refuse a session when the container query fails, rather than assume the session has no containers. It SHALL refuse a session whose lock is held by a live launch, reset or prune, naming the lock and its holder, and SHALL hold that lock itself from its own checks until its deletion is complete.

#### Scenario: Running agent refused
- **WHEN** `tjor prune --session a` names a session with a running agent
- **THEN** the session is refused with a message naming `tjor down`, and its state directory is untouched

#### Scenario: Stopped containers still count as in use
- **WHEN** a session's agent container has exited and nothing of the session is running
- **THEN** prune refuses it the same way, because `tjor down` is the path that removes the containers and runs the teardown git check

#### Scenario: Sidecars only still count as in use
- **WHEN** a session's agent container is gone but its proxy or DNS sidecar still exists
- **THEN** prune refuses it the same way

#### Scenario: A failed container query refuses
- **WHEN** the container daemon stops answering between prune's start and a session's check
- **THEN** that session is refused with the query error, and nothing of it is removed

#### Scenario: A held lock refuses
- **WHEN** a launch of session `a` holds its lock and `tjor prune --session a` runs
- **THEN** the session is refused naming the lock and its holder, and nothing of it is removed

### Requirement: Prune decides under the lock

Age selection is discovery only: for every session selected by `--older-than`, prune SHALL recompute last activity under the session lock and SHALL skip a session that became active since it was selected. A dry run SHALL take the lock the same way, so it reports a held lock exactly where a real run would refuse.

#### Scenario: A session that became active is skipped
- **WHEN** a session selected by `--older-than 30d` is written to after selection and before prune reaches it
- **THEN** prune reports it as skipped and removes nothing of it

#### Scenario: A dry run reports a held lock
- **WHEN** a launch of session `a` holds its lock and `tjor prune --session a --dry-run` runs
- **THEN** the dry run reports the session as refused for the lock

### Requirement: Prune refuses unreviewed state unless told so per session

`tjor prune` SHALL refuse whole-directory deletion of a session whose git-check marker is pending unless `--discard-unreviewed` is given. That flag SHALL be accepted only together with `--session`, never with `--older-than`, so an age sweep cannot discard unreviewed evidence. `--creds-only` removes no git-check evidence and SHALL NOT be refused by a pending marker.

#### Scenario: Pending git-check marker refused
- **WHEN** a selected session's git-check marker is pending
- **THEN** prune refuses its whole-directory deletion, names `tjor git-check --session <id>` as the way to review, and removes nothing for that session

#### Scenario: Discarding unreviewed findings is explicit and per session
- **WHEN** `tjor prune --session a --discard-unreviewed` names a session with a pending marker and no container
- **THEN** the directory is removed and the output says that unreviewed git-check findings were discarded; the same flag with `--older-than` is refused with usage before anything is selected

#### Scenario: Credentials only is not blocked by the marker
- **WHEN** `tjor prune --session a --creds-only` names a session with a pending marker and no container
- **THEN** the credential tier is removed and the git-check baseline and marker remain

### Requirement: Prune deletes through the symlink guard

Every path prune removes SHALL have only real directories between the canonical configured session root and the path's parent; a symbolic link or non-directory anywhere in that prefix SHALL refuse that path loudly and prune SHALL continue with the rest, exiting non-zero at the end. `--creds-only` SHALL remove only the credential tier of each selected session and leave harness history, caches, metadata and git-check evidence in place.

#### Scenario: Planted symlink ancestor refused
- **WHEN** an intermediate directory inside a selected state directory has been replaced by a symbolic link to a location outside the session root, and `--creds-only` targets a path beneath it
- **THEN** that path is refused with a loud message, nothing behind the link is deleted, the other selected paths are still processed, and prune exits non-zero

#### Scenario: Whole directory removed
- **WHEN** `tjor prune --session a` selects an idle session with no container and no pending marker
- **THEN** the entire state directory is removed and no other session's directory is touched

#### Scenario: Credentials only
- **WHEN** `tjor prune --session a --creds-only` runs
- **THEN** the session's credential paths are removed and its harness history, caches and metadata remain

### Requirement: The credential tier is one set

The credential paths that `tjor ls --state` flags, `tjor prune --creds-only` removes and `tjor reset creds` removes SHALL be one set, defined once. It SHALL name every credential path tjor writes into the state directory and every harness credential file the agent images are known to write; the documentation SHALL state which harness locations it does not cover, and that whole-directory prune removes everything regardless.

#### Scenario: One definition
- **WHEN** a state directory holds every path of the credential tier
- **THEN** `tjor ls --state` flags each of them, and after `tjor prune --session <id> --creds-only` none of them remain while the non-credential tiers do
