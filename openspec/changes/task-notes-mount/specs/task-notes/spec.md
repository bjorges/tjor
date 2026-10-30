# Spec Delta

## Purpose
A per-task notes directory the agent can write, resolved from `--task <id>` by user configuration and mounted beside the workspace, so task notes reach the cage without the notes repository they live in becoming the workspace.

## ADDED Requirements

### Requirement: A task resolves a notes directory by user configuration

When `task.notes_dir` is configured, a launch with `--task <id>` SHALL resolve the directory by substituting the id into the template and SHALL mount it writable at its host path as an additional writable root, through the same path as a `--dir` argument, so every rule that governs extra writable roots applies to it unchanged. Workspace resolution SHALL be unaffected. The `[task]` table SHALL be read from the defaults and the user config only. Without the setting, `--task` SHALL keep today's behaviour exactly.

#### Scenario: Notes mounted beside the workspace
- **WHEN** `task.notes_dir = "~/scratch/tasks/{task}"` is in the user config and `tjor run --task a` is launched from a repository
- **THEN** the workspace is that repository, `~/scratch/tasks/a` is mounted writable at its host path, and the repository's trusted `.tjor/policy.toml` and `.tjor/config.toml` and the harness's instruction discovery resolve from the repository as before

#### Scenario: The mount inherits every extra-dir rule
- **WHEN** the resolved notes directory is a sensitive host path, or lies under a read-only root
- **THEN** the launch is refused with the same error the equivalent `--dir` would produce

#### Scenario: Already covered by a writable root
- **WHEN** the resolved notes directory lies under the workspace or under a `--dir` root
- **THEN** it is not mounted a second time, and `TJOR_TASK_DIR` still names it

#### Scenario: Unchanged without configuration
- **WHEN** no `task.notes_dir` is configured and `tjor run --task A` is launched
- **THEN** nothing is mounted for the task, the task id grammar, the session name and every command behave as before

### Requirement: The notes template is absolute and names the task once

`task.notes_dir` SHALL be an absolute path (a leading `~` expands) holding the placeholder `{task}` exactly once; its fixed prefix is everything before the component holding the placeholder, and the prefix SHALL exist as a real directory. Any other template SHALL refuse the launch before any session state exists.

#### Scenario: Malformed template
- **WHEN** `task.notes_dir` is relative, holds no `{task}`, holds it twice, or its prefix does not exist
- **THEN** the launch is refused naming the setting, before any session state exists

### Requirement: A task id that resolves to a path is a plain lower-case name

When a notes directory is configured, a task id SHALL match `[a-z0-9][a-z0-9_-]{0,31}`: no dot (so `.`, `..` and hidden names are impossible), no upper case (one spelling per directory on every filesystem) and at most 32 characters (it is also the session's short name). Without a configured notes directory the id grammar SHALL be unchanged.

#### Scenario: Ids outside the grammar refused
- **WHEN** `--task ..`, `--task .notes`, `--task JIRA-123` or a 33-character id is given with a notes directory configured
- **THEN** the launch is refused naming the id and the grammar, and no directory is created

#### Scenario: Label-only ids unchanged
- **WHEN** no notes directory is configured and `--task JIRA-123` or `--task .notes` is given
- **THEN** the id is accepted as a label, as before

### Requirement: The directory is created on the launch path only, below the prefix

Resolution SHALL have no side effect, so lifecycle commands that resolve a session never create anything. On the launch path, after the sensitive-path gate has accepted the resolved path and the session lock is held, the directory SHALL be created when `task.create` is true, one component at a time below the prefix, each step opened relative to its parent without following links and verified to be a real directory; the prefix SHALL never be created. A symbolic link below the prefix SHALL refuse the launch naming it. With `task.create` false a missing directory SHALL refuse the launch.

#### Scenario: A symlink below the prefix
- **WHEN** `~/scratch/tasks/a` is a symbolic link, wherever it points
- **THEN** the launch is refused naming the link, and nothing it points to is mounted

#### Scenario: Creation below the prefix only
- **WHEN** `task.create` is true, `~/scratch/tasks` exists and `a/notes` does not, with the template `~/scratch/tasks/{task}/notes`
- **THEN** `a` and then `notes` are created as real directories after the gate, and the prefix `~/scratch/tasks` is never created by tjor

#### Scenario: Sensitive template refused before creation
- **WHEN** the template resolves under a sensitive path such as `~/.ssh/{task}`
- **THEN** the launch is refused by the sensitive-path gate and no directory is created

#### Scenario: Lifecycle commands create nothing
- **WHEN** `tjor status --session a` runs for a task whose directory does not exist
- **THEN** no directory is created

#### Scenario: Missing directory with creation off
- **WHEN** `task.create` is false and the resolved directory does not exist
- **THEN** the launch is refused naming the directory

### Requirement: The notes repository never becomes the workspace

A launch SHALL be refused, with no override, when the resolved workspace is the notes root (the template's fixed prefix) or an ancestor of it. The comparison SHALL be by filesystem identity (device and inode along the parent chain), never by path string, so a case-insensitive or Unicode-normalising filesystem cannot make two spellings of one directory read as different. The refusal SHALL name both paths.

#### Scenario: Launched from inside the notes repository
- **WHEN** `~/scratch` is a git repository, `task.notes_dir = "~/scratch/tasks/{task}"`, and `tjor run --task a` is launched from `~/scratch/tasks/a`
- **THEN** the launch is refused, because the workspace `~/scratch` contains the notes root, and no state directory is created

#### Scenario: Another spelling of the same root
- **WHEN** the workspace is reached through a differently-cased or differently-composed spelling of the notes root on a filesystem that treats them as one directory
- **THEN** the launch is refused all the same

#### Scenario: Workspace below the notes root
- **WHEN** the workspace is a repository at `~/scratch/tasks/a/repo` under the same configuration
- **THEN** the launch proceeds: the workspace is not an ancestor of the notes root

### Requirement: An empty notes directory is still share-checked

When the resolved directory is empty at launch, the VM-share verification SHALL run on the notes root instead, which holds at least that directory, so an unshared path is refused rather than silently landing in a VM-side directory the host never sees.

#### Scenario: Fresh directory on an unshared path
- **WHEN** `task.create` just created the directory and the notes root is not shared with the container runtime
- **THEN** the launch is refused naming the notes root, before the agent starts

### Requirement: The notes directory is named inside the cage only

The agent environment SHALL carry `TJOR_TASK_DIR`, the notes directory's host path, which is also its path inside the cage. No identity header SHALL be derived from it; the task id, which is the directory's basename by construction, travels as `x-agent-task-id` as today.

#### Scenario: Visible to the agent, no header derived
- **WHEN** a session with a notes directory sends a request toward an `inject_hosts` destination
- **THEN** `TJOR_TASK_DIR` is set in the agent's environment, no header carries the directory's path, and a forged `x-agent-task-dir` header is stripped like any unknown identity header

### Requirement: Credential-shaped files in the notes directory are announced

Before the agent starts, the launcher SHALL scan the notes directory, bounded in depth, entry count and bytes read, never following links and reading only regular files, for file names shaped like credentials (a name segment `token`, `credentials`, `secret` or `password`; `.netrc`, `.npmrc`, `kubeconfig`; `*.pem`, `*.key`, `*.p12`, `*.pfx`; `id_*`) and for the secret shapes the egress tripwire detects in content, and SHALL print a loud warning naming each match through the terminal-escape sanitizer. A scan that reached a bound or could not read a file SHALL say so. The scan SHALL NOT refuse the launch and SHALL NOT alter a file.

#### Scenario: A private key among the notes
- **WHEN** the notes directory holds `deploy.pem` and a text file containing a GitHub token shape
- **THEN** the launch prints a warning naming both files and continues

#### Scenario: Clean directory
- **WHEN** the notes directory holds only ordinary notes, `tokenizer.md` included
- **THEN** no warning is printed

#### Scenario: Partial scan is not silent
- **WHEN** the directory holds more entries than the bound, or a file that cannot be opened, or a FIFO
- **THEN** the warning states that the scan was partial and why, and the FIFO is skipped without blocking the launch

### Requirement: The notes directory's residuals are stated

The README SHALL state: the directory is writable and git-trusted as a tree like any `--dir`; every session launched with the same task id shares it; what the agent writes there reaches the host, including nested repositories, links and committed secrets a host-side notes repository may then pick up; and the bind source is handed to the container engine as a path, so a component swapped after the launcher's checks is outside what it can see.

#### Scenario: Residuals in the README
- **WHEN** the README's task-notes section is read
- **THEN** each residual above is stated plainly
