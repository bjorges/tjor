# Spec Delta

## MODIFIED Requirements

### Requirement: A task resolves a notes directory by user configuration

When `task.notes_dir` is configured, a launch with `--task <id>` SHALL resolve the directory from the template and mount it writable at its host path as an additional writable root, through the same path as a `--dir` argument, so every rule for extra writable roots applies unchanged. Workspace resolution SHALL be unaffected; the `[task]` table is read from the defaults and the user config only; with no `[task]` key set (`notes_dir`, `session_per_task`, `prompt`, `resume`), `--task` SHALL behave exactly as today.

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
- **WHEN** no `[task]` key is set and `tjor run --task A` is launched
- **THEN** nothing is mounted for the task, no prompt is sent, the task id grammar, the session name and every command behave as before
