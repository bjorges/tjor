## MODIFIED Requirements

### Requirement: Git hook directories are masked at launch

By default (`[landlock] mask_git_hooks = true`), the launcher SHALL mask the hooks directory of every git directory it discovers under a **writable** mount root at launch — the workspace repository, each `--dir` repository, repositories nested under a mounted parent, the common git directory of a linked worktree when that directory lies under a writable root, and a writable mount root that is itself a git directory (a worktree's common directory mounted alongside it, whatever its name) — with a read-only empty bind mount, exactly as configured directory masks are applied. A repository whose hooks directory is absent at launch SHALL have an empty one created on the host so the mask has a mountpoint. From inside the cage a masked hooks directory SHALL list empty, nothing SHALL be creatable in it, it SHALL NOT be removable or replaceable, and git SHALL run no hook from it. Each mask SHALL be announced at launch with the path rendered escape-sanitized. Read-only mount roots need no mask and SHALL get none. Setting `mask_git_hooks = false` SHALL disable the mask; the documentation SHALL state that host-installed hooks then fire on in-cage commits again. Documentation SHALL state the residuals honestly: `core.hooksPath` bypasses the hooks mask (the config pin below is the preventive answer); a repository created inside the cage after launch is not masked; sibling repositories under one writable parent are not isolated from each other. A `.git` entry, a hooks directory or a config file that is a symbolic link SHALL be refused at launch and never masked or pinned through (the mask would land on the link's target, a path a previous session could have chosen); the refusal SHALL name the link, its target, the fix and the opt-out. Discovery SHALL NOT descend below a `.git` directory.

#### Scenario: Workspace hooks directory is structurally empty
- **WHEN** the workspace repository has `.git/hooks/pre-commit` at launch
- **THEN** listing `.git/hooks` inside the cage shows no entries, creating a file there fails, and the launch announced the mask

#### Scenario: A host-installed hook does not fire in-cage
- **WHEN** the workspace repository carries a `pre-commit` hook that writes a marker when run, and the agent commits inside the cage
- **THEN** the commit succeeds and the marker is never written

#### Scenario: Nested repository and worktree common directory are masked too
- **WHEN** a mounted parent contains a nested repository, and a linked worktree whose common git directory lies under the same writable root
- **THEN** both the nested repository's hooks directory and the common directory's hooks directory are masked

#### Scenario: A mounted worktree common directory is masked
- **WHEN** a session launches from a linked worktree whose main repository lies outside the workspace and carries a `pre-commit` hook
- **THEN** the common directory's hooks directory is masked, lists empty in-cage, and the hook does not fire on an in-cage commit

#### Scenario: Opt-out restores host hooks
- **WHEN** `mask_git_hooks = false` is configured
- **THEN** no hooks directory is masked and the launch announces none

#### Scenario: A symlinked hooks directory refuses the launch
- **WHEN** a writable repository's `.git/hooks` (or its `.git` entry) is a symbolic link at launch
- **THEN** the launch is refused before any container starts, naming the link, its target, the fix and the opt-out
