## ADDED Requirements

### Requirement: A linked worktree's common git directory is mounted alongside it

For every mount root — the workspace, each `--dir` and each `--dir-ro` — whose `.git` entry is a file, the launcher SHALL resolve the root's git directory and common git directory through git (a read-only resolution that executes nothing configured in the repository) and SHALL accept them only when: the common directory is a git directory (it holds `HEAD`, `objects` and `refs`); and either the private directory's back-pointer (`<common>/worktrees/<name>/gitdir`) names this root's own `.git` file (a linked worktree), or the git directory's `core.worktree` names this root (a separate git directory). An accepted common directory that does not already lie under a mount root SHALL be mounted at its host path with the root's writability class and announced at launch naming the worktree it serves; one that lies under a read-only root while the worktree is writable SHALL be announced as read-only with the consequence stated. The launcher SHALL refuse the launch, before any container starts and naming the reason, when git cannot resolve the pointer, when the linkage does not point back at the root, when the `.git` entry is a symbolic link, or when the common directory is a sensitive host path; `--unsafe-dir` SHALL NOT override a sensitive common directory. A mounted common directory SHALL be a mount root in every other respect: git trust, the kernel tier's grants, the mixed-writability rule, launch-time masks and the git-check baseline. Two roots that share one common directory SHALL mount it once, writable if either root is writable.

#### Scenario: Git works inside a worktree workspace
- **WHEN** a session launches from a linked worktree whose main repository lies outside the workspace
- **THEN** the launch announces the common directory mount, and `git status`, `git log` and `git commit` succeed inside the cage

#### Scenario: A planted pointer is refused
- **WHEN** a mount root's `.git` file names a git directory whose worktree linkage does not point back at that root
- **THEN** the launch is refused before any container starts, naming the mismatch, and nothing is mounted for the pointer

#### Scenario: A pointer git cannot resolve is refused
- **WHEN** a mount root's `.git` file names a path that is not a git directory
- **THEN** the launch is refused with the pointer and the path named, instead of the cage failing later

#### Scenario: A common directory already under a mount root needs no extra mount
- **WHEN** the worktree and its main repository both lie under one writable mount root
- **THEN** no additional mount is added and the launch announces none
