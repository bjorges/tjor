# task-notes Specification

## Purpose
A per-task notes directory the agent can write, resolved from `--task <id>` by user configuration and mounted beside the workspace, so task notes reach the cage without the notes repository they live in becoming the workspace.

## Requirements

### Requirement: A task resolves a notes directory by user configuration

When `task.notes_dir` is configured, a launch with `--task <id>` SHALL resolve the directory from the template and mount it writable at its host path as an additional writable root, through the same path as a `--dir` argument, so every rule for extra writable roots applies unchanged. Workspace resolution SHALL be unaffected; the `[task]` table is read from the defaults and the user config only; with every `[task]` key at its default (`notes_dir`, `create`, `session_per_task`, `prompt`, `resume`), `--task` SHALL behave exactly as today.

#### Scenario: Notes mounted beside the workspace
- **WHEN** `task.notes_dir = "~/scratch/tasks/{task}"` is in the user config and `tjor run --task a` is launched from a repository
- **THEN** the workspace is that repository, `~/scratch/tasks/a` is mounted writable at its host path, and the repository's trusted `.tjor/policy.toml` and `.tjor/config.toml` and the harness's instruction discovery resolve from the repository as before

#### Scenario: The mount inherits every extra-dir rule
- **WHEN** the resolved notes directory is a sensitive host path, or lies under a read-only root
- **THEN** the launch is refused with the same error the equivalent `--dir` would produce

#### Scenario: Already covered by a writable root
- **WHEN** the resolved notes directory lies under a `--dir` root
- **THEN** it is still created or validated and scanned, it is not mounted a second time, and `TJOR_TASK_DIR` names it

#### Scenario: A notes root inside the workspace is the notes-repository case
- **WHEN** the template's root lies under the workspace (`~/proj/notes/{task}` launched from `~/proj`)
- **THEN** the launch is refused by the notes-root rule, because the workspace contains the notes root

#### Scenario: Coverage that cannot be established
- **WHEN** the identity walk that decides coverage or the notes-root refusal fails (a component vanished, a permission error)
- **THEN** the launch is refused naming the error; an error is never read as "not covered" or "not contained"

#### Scenario: Unchanged without configuration
- **WHEN** every `[task]` key is at its default and `tjor run --task A` is launched
- **THEN** nothing is mounted for the task, no prompt is sent, no continue flag is added, no launch record is written, and the task id grammar, the session name and every command behave as before

### Requirement: The notes template is absolute and names the task once

`task.notes_dir` SHALL be an absolute path (a leading `~` expands) whose components, checked one by one, are each non-empty and neither `.` nor `..`, with a single leading separator and no trailing one, holding the placeholder `{task}` exactly once inside one component; its fixed prefix is everything before that component, and the prefix SHALL exist as a real directory. Any other template SHALL refuse the launch before any session state exists.

#### Scenario: Malformed template
- **WHEN** `task.notes_dir` is relative, holds no `{task}`, holds it twice, or its prefix does not exist
- **THEN** the launch is refused naming the setting, before any session state exists

#### Scenario: Traversal in the template
- **WHEN** `task.notes_dir` is `/safe/tasks/{task}/../../elsewhere`, `/safe/tasks/{task}//notes`, `//safe/tasks/{task}` or `/safe/tasks/{task}/`
- **THEN** the launch is refused naming the setting, and nothing is created or mounted

### Requirement: A task id that resolves to a path is a plain lower-case name

When a notes directory is configured or `task.session_per_task` is enabled, a task id SHALL match `[a-z0-9][a-z0-9_-]{0,31}`: no dot (so `.`, `..` and hidden names are impossible), no upper case (one spelling per directory on every filesystem) and at most 32 characters (it is also the session's short name). With neither setting the id grammar SHALL be unchanged.

#### Scenario: Ids outside the grammar refused
- **WHEN** `--task ..`, `--task .notes`, `--task JIRA-123` or a 33-character id is given with a notes directory configured
- **THEN** the launch is refused naming the id and the grammar, and no directory is created

#### Scenario: Label-only ids unchanged
- **WHEN** neither `task.notes_dir` nor `task.session_per_task` is set and `--task JIRA-123` or `--task .notes` is given
- **THEN** the id is accepted as a label, as before

### Requirement: The directory is created on the launch path only, below the prefix

Resolution SHALL have no side effect, so lifecycle commands never create anything. On the launch path the order SHALL be: gate the intended path; under the session lock create (when `task.create` is true) or validate the directory, one component at a time below the prefix, each opened relative to its parent without following links and verified to be a real directory; judge coverage; mount; scan. A link below the prefix, or a missing directory with `task.create` false, SHALL refuse the launch.

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

#### Scenario: What a refusal leaves behind, precisely
- **WHEN** the launch is refused by the template, the id, the notes-root rule, the sensitive-path gate or the creation walk
- **THEN** no notes directory and no session state directory were created; a refusal by the share probe comes later, after session state and sidecars exist, as for every extra-dir share check

#### Scenario: Missing directory with creation off
- **WHEN** `task.create` is false and the resolved directory does not exist
- **THEN** the launch is refused naming the directory

### Requirement: The notes repository never becomes the workspace

A launch SHALL be refused, with no override, when the resolved workspace is the notes root (the template's fixed prefix) or an ancestor of it. The comparison SHALL be by filesystem identity (device and inode along the parent chain), never by path string, so a case-insensitive or Unicode-normalising filesystem cannot make two spellings of one directory read as different. Both paths SHALL be the launcher's physical spellings, walked without following a link: a link anywhere on either chain, or a `.` or `..` component, SHALL refuse the launch rather than be followed or collapsed. The refusal SHALL name both paths.

#### Scenario: Launched from inside the notes repository
- **WHEN** `~/scratch` is a git repository, `task.notes_dir = "~/scratch/tasks/{task}"`, and `tjor run --task a` is launched from `~/scratch/tasks/a`
- **THEN** the launch is refused, because the workspace `~/scratch` contains the notes root, and no state directory is created

#### Scenario: Another spelling of the same root
- **WHEN** the workspace is reached through a differently-cased or differently-composed spelling of the notes root on a filesystem that treats them as one directory
- **THEN** the launch is refused all the same

#### Scenario: Workspace below the notes root
- **WHEN** the workspace is a repository at `~/scratch/tasks/a/repo` under the same configuration
- **THEN** the launch proceeds: the workspace is not an ancestor of the notes root

### Requirement: The share check for the notes directory uses a probe file

Because a fresh directory is empty and the generic bind-source check compares content only, the notes directory SHALL be verified, covered or not, by a probe: an empty file with an unpredictable name created in the directory itself, which a throwaway container with the directory bound read-only and nothing else must see; the probe SHALL be removed afterwards whatever the outcome. A container that does not see the probe SHALL refuse the launch naming the directory.

#### Scenario: Fresh directory on an unshared path
- **WHEN** `task.create` just created the directory and it is not shared with the container runtime
- **THEN** the launch is refused naming the directory, before the agent starts, and no probe file remains

#### Scenario: A VM-side directory of the same name
- **WHEN** the container runtime holds a stale directory at the same path with other content
- **THEN** the probe is not seen and the launch is refused all the same

#### Scenario: The probe container is isolated
- **WHEN** the probe runs
- **THEN** it uses the pinned proxy image with a plain shell entrypoint, `--network none`, a read-only bind of the notes directory only, no environment and no socket, and the probe name is passed as an argument, never interpolated into a shell string

### Requirement: The notes directory is named inside the cage only

The agent environment SHALL carry `TJOR_TASK_DIR`, the notes directory's host path in its physical spelling (the resolved prefix plus the components below it, even when the template spells the prefix through a link), which is also its path inside the cage; the sensitive-path gate, the coverage checks, the `--dir-ro` conflict check, the mount and the scan SHALL all use that one spelling. No identity header SHALL be derived from it; the task id travels as `x-agent-task-id` as today, the directory's path does not.

#### Scenario: Visible to the agent, no header derived
- **WHEN** a session with a notes directory sends a request toward an `inject_hosts` destination
- **THEN** `TJOR_TASK_DIR` is set in the agent's environment, no header carries the directory's path, and a forged `x-agent-task-dir` header is stripped like any unknown identity header

### Requirement: Credential-shaped files in the notes directory are announced

Before the agent starts, the launcher SHALL scan the notes directory, bounded in depth, entries and bytes, without following links and reading only regular files, for credential-shaped names and for the secret shapes the egress tripwire detects in content, and SHALL print a loud warning naming up to ten matches and the total, each through the terminal-escape sanitizer. A partial scan SHALL say so. The scan SHALL NOT refuse the launch and SHALL NOT alter a file.

#### Scenario: Names that count as credential-shaped
- **WHEN** the directory holds files whose name has a segment `token`, `credentials`, `secret` or `password`, is `.netrc`, `.npmrc` or `kubeconfig`, ends in `.pem`, `.key`, `.p12` or `.pfx`, or starts with `id_`
- **THEN** each is named in the warning with the reason

#### Scenario: A private key among the notes
- **WHEN** the notes directory holds `deploy.pem` and a text file containing a GitHub token shape
- **THEN** the launch prints a warning naming both files and continues

#### Scenario: Clean directory
- **WHEN** the notes directory holds only ordinary notes, `tokenizer.md` included
- **THEN** no warning is printed

#### Scenario: Partial scan is not silent
- **WHEN** the directory holds more entries than the bound, or a file that cannot be opened, or a FIFO
- **THEN** the warning states that the scan was partial and why, naming the skipped entry, and the FIFO is skipped without blocking the launch

#### Scenario: Hostile file names cannot corrupt the report
- **WHEN** a finding's name holds a tab, a newline or a terminal escape
- **THEN** the report line stays one line and the name is rendered through the sanitizer

### Requirement: The notes directory's residuals are stated

The README SHALL state each residual in the scenario below plainly.

#### Scenario: Residuals in the README
- **WHEN** the README's task-notes section is read
- **THEN** it states that the directory is writable and git-trusted as a tree like any `--dir`; that every session launched with the same task id shares it, and one task id is one session for every harness unless `--session` names one; that what the agent writes there reaches the host, including nested repositories, links and committed secrets a host-side notes repository may then pick up; that the bind source is handed to the container engine as a path, so a component swapped after the launcher's checks is outside what it can see; and that a probe file may remain if tjor is killed during the share check
