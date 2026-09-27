# Spec Delta

## ADDED Requirements

### Requirement: Git hook directories are masked at launch

By default (`[landlock] mask_git_hooks = true`), the launcher SHALL mask the hooks directory of every git directory it discovers under a **writable** mount root at launch — the workspace repository, each `--dir` repository, repositories nested under a mounted parent, and the common git directory of a linked worktree when that directory lies under a writable root — with a read-only empty bind mount, exactly as configured directory masks are applied. A repository whose hooks directory is absent at launch SHALL have an empty one created on the host so the mask has a mountpoint. From inside the cage a masked hooks directory SHALL list empty, nothing SHALL be creatable in it, it SHALL NOT be removable or replaceable, and git SHALL run no hook from it. Each mask SHALL be announced at launch with the path rendered escape-sanitized. Read-only mount roots need no mask and SHALL get none. Setting `mask_git_hooks = false` SHALL disable the mask; the documentation SHALL state that host-installed hooks then fire on in-cage commits again. Documentation SHALL state the residuals honestly: `core.hooksPath` bypasses the hooks mask (the config pin below is the preventive answer); a repository created inside the cage after launch is not masked; sibling repositories under one writable parent are not isolated from each other.

#### Scenario: Workspace hooks directory is structurally empty
- **WHEN** the workspace repository has `.git/hooks/pre-commit` at launch
- **THEN** listing `.git/hooks` inside the cage shows no entries, creating a file there fails, and the launch announced the mask

#### Scenario: A host-installed hook does not fire in-cage
- **WHEN** the workspace repository carries a `pre-commit` hook that writes a marker when run, and the agent commits inside the cage
- **THEN** the commit succeeds and the marker is never written

#### Scenario: Nested repository and worktree common directory are masked too
- **WHEN** a mounted parent contains a nested repository, and a linked worktree whose common git directory lies under the same writable root
- **THEN** both the nested repository's hooks directory and the common directory's hooks directory are masked

#### Scenario: Opt-out restores host hooks
- **WHEN** `mask_git_hooks = false` is configured
- **THEN** no hooks directory is masked and the launch announces none

### Requirement: Operator can pin git config read-only

When `[landlock] protect_git_config = true` is configured (default `false`), the launcher SHALL pin each discovered git directory's `config` file (the common directory's for a linked worktree) read-only with a single-file bind of the real file over itself, for every git directory under a writable mount root, and SHALL announce each pin. Reads of the file SHALL work; every write, including git's own lock-and-rename, SHALL fail. The documentation SHALL list the in-cage operations this breaks (`git config`, `git remote add`, `push -u`, `branch --set-upstream-to`, `worktree add -b` with tracking, `gh pr checkout`) and those that keep working (`commit`, `push` without `-u`, `fetch`, `status`, `log`, `diff`), and SHALL state that this is the only preventive control here against `core.hooksPath`, `core.fsmonitor` and filter-driver redirection. These masks are mask-class mounts (read-only binds inside a writable tree), the same class as the dotenv masks, and are not subject to the mixed-writability mount rule.

#### Scenario: Config writes fail, commits work
- **WHEN** the pin is enabled and, inside the cage, the agent runs `git config x.y z`, `git remote add o https://example.invalid/r`, then `git commit`
- **THEN** the two config writes fail, the file is unchanged, and the commit succeeds

#### Scenario: Config stays readable
- **WHEN** the pin is enabled
- **THEN** `git config --list` and `git remote -v` inside the cage succeed

#### Scenario: Default is off
- **WHEN** `protect_git_config` is not configured
- **THEN** no config file is pinned and `git config x.y z` inside the cage succeeds
