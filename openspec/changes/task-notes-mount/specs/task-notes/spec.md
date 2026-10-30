# Spec Delta

## Purpose
A per-task notes directory the agent can write, resolved from `--task <id>` by configuration and mounted beside the workspace, so task notes reach the cage without the notes repository they live in becoming the workspace.

## ADDED Requirements

### Requirement: A task resolves a notes directory by configuration

When `task.notes_dir` is configured, a launch with `--task <id>` SHALL resolve the directory by substituting the id into the template and SHALL mount it writable at its host path as an additional writable root, through the same path as a `--dir` argument, so every rule that governs extra writable roots applies to it unchanged. Workspace resolution SHALL be unaffected. Without the setting, `--task` SHALL keep today's behaviour exactly.

#### Scenario: Notes mounted beside the workspace
- **WHEN** `task.notes_dir = "~/scratch/tasks/{task}"` is configured and `tjor run --task A` is launched from a repository
- **THEN** the workspace is that repository, `~/scratch/tasks/A` is mounted writable at its host path, and the repository's trusted `.tjor/policy.toml` and `.tjor/config.toml` and the harness's instruction discovery resolve from the repository as before

#### Scenario: The mount inherits every extra-dir rule
- **WHEN** the resolved notes directory is a sensitive host path, is not shared with the container runtime, or overlaps a read-only root
- **THEN** the launch is refused with the same error the equivalent `--dir` would produce

#### Scenario: Unchanged without configuration
- **WHEN** no `task.notes_dir` is configured and `tjor run --task A` is launched
- **THEN** nothing is mounted for the task, the task id grammar, the session name and every command behave as before

### Requirement: The notes template is absolute and names the task once

`task.notes_dir` SHALL be an absolute path (a leading `~` expands) holding the placeholder `{task}` exactly once; its fixed prefix is everything before the component holding the placeholder. Any other template SHALL refuse the launch before any session state exists.

#### Scenario: Malformed template
- **WHEN** `task.notes_dir` is relative, holds no `{task}`, or holds it twice
- **THEN** the launch is refused naming the setting, before any session state exists

### Requirement: A task id that resolves to a path may not start with a dot

When a notes directory is configured, a task id SHALL NOT start with a dot, so `.`, `..` and hidden names are refused before any path is formed. Without a configured notes directory the id grammar SHALL be unchanged.

#### Scenario: Dot-leading ids refused
- **WHEN** `--task ..` or `--task .notes` is given with a notes directory configured
- **THEN** the launch is refused naming the id, and no directory is created

#### Scenario: Label-only ids unchanged
- **WHEN** no notes directory is configured and `--task .notes` is given
- **THEN** the id is accepted as a label, as before

### Requirement: The resolved directory stays under the template's prefix

The directory's physical path SHALL lie under the physical path of the fixed prefix; a symbolic link anywhere below the prefix that leads elsewhere SHALL refuse the launch, naming the link. The directory SHALL be created only when `task.create` is true, component by component below the prefix, each existing level verified to be a real directory before the next is made, and the prefix itself SHALL never be created; with `task.create` false a missing directory SHALL refuse the launch.

#### Scenario: A symlink escaping the prefix
- **WHEN** `~/scratch/tasks/A` is a symbolic link to a directory outside `~/scratch/tasks`
- **THEN** the launch is refused naming the link and its target's location, and nothing outside the prefix is mounted

#### Scenario: Creation below the prefix only
- **WHEN** `task.create` is true, `~/scratch/tasks` exists and `A/notes` does not, with the template `~/scratch/tasks/{task}/notes`
- **THEN** `A` and then `notes` are created as real directories, and the prefix `~/scratch/tasks` is never created by tjor

#### Scenario: Missing directory with creation off
- **WHEN** `task.create` is false and the resolved directory does not exist
- **THEN** the launch is refused naming the directory

### Requirement: The notes repository never becomes the workspace

A launch SHALL be refused, with no override, when the resolved workspace equals the notes root (the template's fixed prefix) or is an ancestor of it. The refusal SHALL name both paths and point at `--workspace <dir>` and `--notes-workspace`.

#### Scenario: Launched from inside the notes repository
- **WHEN** `~/scratch` is a git repository, `task.notes_dir = "~/scratch/tasks/{task}"`, and `tjor run --task A` is launched from `~/scratch/tasks/A`
- **THEN** the launch is refused, because the workspace `~/scratch` contains the notes root, and no state directory is created

#### Scenario: Workspace below the notes root
- **WHEN** the workspace is a repository at `~/scratch/tasks/A/repo` under the same configuration
- **THEN** the launch proceeds: the workspace is not an ancestor of the notes root

### Requirement: The notes directory is named inside the cage only

The agent environment SHALL carry `TJOR_TASK_DIR`, the notes directory's host path, which is also its path inside the cage. The value SHALL NOT be part of the `x-agent-*` wire schema and SHALL be absent from every outbound request.

#### Scenario: Visible to the agent, absent on the wire
- **WHEN** a session with a notes directory sends a request toward an `inject_hosts` destination
- **THEN** `TJOR_TASK_DIR` is set in the agent's environment and no header carries the directory path, in full or in part

### Requirement: A repo-less task can use its notes directory as the workspace

`tjor run --notes-workspace --task <id>` SHALL make the resolved notes directory the workspace exactly: no version-control discovery is run for it, nothing above it is mounted, and the sensitive-path gate and the credential-shaped-file scan apply to it as to any workspace. The option SHALL require `--task` and a configured `task.notes_dir`, and SHALL be refused together with `--workspace`.

#### Scenario: Notes directory inside a notes repository
- **WHEN** `~/scratch` is a git repository and `tjor run --notes-workspace --task A` is launched
- **THEN** the workspace is `~/scratch/tasks/A`, `~/scratch` is not mounted, and the session id derives from `~/scratch/tasks/A`

#### Scenario: Missing prerequisites
- **WHEN** `--notes-workspace` is given without `--task`, without `task.notes_dir`, or together with `--workspace`
- **THEN** the launch is refused with a usage error

### Requirement: Credential-shaped files in the notes directory are announced

Before the agent starts, the launcher SHALL scan the notes directory, bounded in depth, entry count and bytes read, for file names shaped like credentials (`token` in the name, `*.pem`, `*.key`, `id_*`) and for the secret shapes the egress tripwire detects in file content, and SHALL print a loud warning naming each match (rendered through the terminal-escape sanitizer) when any is found. The scan SHALL NOT refuse the launch and SHALL NOT alter a file.

#### Scenario: A private key among the notes
- **WHEN** the notes directory holds `deploy.pem` and a text file containing a GitHub token shape
- **THEN** the launch prints a warning naming both files and continues

#### Scenario: Clean directory
- **WHEN** the notes directory holds only ordinary notes
- **THEN** no warning is printed
