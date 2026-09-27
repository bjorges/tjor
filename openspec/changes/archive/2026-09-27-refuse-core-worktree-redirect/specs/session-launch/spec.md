# Spec Delta

## ADDED Requirements

### Requirement: The resolved workspace must be the repository found above the launch directory

When the launcher resolves the workspace through version-control discovery, it SHALL independently locate the repository the launch directory belongs to — the nearest ancestor of the physical launch directory, itself included, that holds a `.git` entry (a directory for a plain repository, a file for a linked worktree or submodule) — and SHALL accept git's reported toplevel only if it is that directory. Otherwise the launcher SHALL refuse — on the launch path and on every lifecycle-command path (`down`, `status`, `reset`, `denials`) alike — with an error naming the launch directory, the reported work tree, the repository it found, the `core.worktree` value and the config file carrying it when one is set, and the remedy. There SHALL be no override: a repository whose configured work tree is elsewhere is never a tjor workspace. Rationale (normative): a session always holds its workspace repository writable, so it can plant `core.worktree`; git then reports the planted path as the toplevel from anywhere inside the repository — a sibling, an ancestor such as the directory holding every repository the operator owns, or the home directory — and the next host-side launch would silently adopt it as the workspace (mounted writable, git-trusted as a tree, under a session id derived from it), or a lifecycle command would act on another session. Containment of the launch directory is not sufficient, because an ancestor redirect still contains it. Every honest resolution (a plain repository, a subdirectory of one, a linked worktree, a submodule, a nested repository, a symlinked spelling) agrees with the independent discovery.

#### Scenario: Redirect toward an ancestor holding other repositories is refused
- **WHEN** a repository's `.git/config` sets `core.worktree` to a parent directory of the repository (one that holds other repositories), and `tjor run` is invoked from inside that repository
- **THEN** the launch aborts naming the repository the launcher found and the `core.worktree` value, and no state directory is created

#### Scenario: Redirect toward a harmless directory is refused
- **WHEN** a repository's `.git/config` sets `core.worktree` to another directory that is not in the sensitive set, and `tjor run` is invoked from inside that repository
- **THEN** the launch aborts naming the launch directory, the reported work tree, the `core.worktree` value and the config file, and no state directory is created

#### Scenario: Redirect toward a sensitive path is reported as a redirect
- **WHEN** `core.worktree` points at the home directory and `tjor run` is invoked from inside the repository
- **THEN** the launch aborts with the containment error naming `core.worktree`, not with the not-a-repository wording

#### Scenario: Linked worktree still launches
- **WHEN** `tjor run` is invoked from a linked worktree created with `git worktree add`
- **THEN** the workspace is that worktree and the launch proceeds

#### Scenario: Subdirectory launch unchanged
- **WHEN** `tjor run` is invoked from a subdirectory of an ordinary repository
- **THEN** the workspace is the repository root and the launch proceeds

#### Scenario: Lifecycle commands refuse a redirect too
- **WHEN** `tjor down` (or `status`, `reset`, `denials`) is invoked from inside a repository whose `core.worktree` points elsewhere
- **THEN** the command refuses with the containment error rather than acting on the session derived from the redirected path
