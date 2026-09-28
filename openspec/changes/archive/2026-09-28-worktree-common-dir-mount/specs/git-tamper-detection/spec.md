## MODIFIED Requirements

### Requirement: A launch records a git-metadata baseline out of the agent's reach

At launch, once the mount set is final, the launcher SHALL record for every git directory discovered under a writable mount root: the dangerous configuration keys present with every value of each (the documented set covering hooks, editors and pagers, ssh, credential, mail and IMAP commands, filter, diff and merge drivers, trailer and GUI tool commands, shell aliases, includes, template directories, remote helpers and proxies, URL rewrites, protocol allow-lists, `safe.*` and `extensions.*`, and a remote or submodule URL naming the `ext::` or `fd::` transport), whether the config file, the `.git` entry and the hooks directory are symbolic links, every worktree pointer (`.git` files and `worktrees/*/gitdir`, `commondir`), a hash of every hook file, and the nested repositories already present in the working tree. Discovery SHALL walk each root once, never follow symbolic links, never descend below a `.git` directory, and stop `git_check_depth` levels below a root (default 32); every spot where the walk stopped — a directory at the cap that still has subdirectories, or one that could not be read — SHALL be recorded in the snapshot and announced at launch. A mount root that is itself a git directory (a worktree's common directory mounted alongside it) SHALL NOT be walked for repositories; its configuration, hooks and worktree pointers are recorded through the worktree that links to it. A config file git cannot parse SHALL be recorded as unreadable, never as having no dangerous keys. The baseline and a pending-check marker SHALL be stored under the session state directory, outside every path mounted into the cage; the marker SHALL be written atomically. The launch SHALL announce the number of repositories baselined.

#### Scenario: Baseline covers every writable root
- **WHEN** a session launches with a workspace and a `--dir` repository, one of them holding a nested repository
- **THEN** the baseline holds an entry for each of the three git directories and the pending marker exists before the agent starts

#### Scenario: A truncated walk is announced
- **WHEN** a writable root holds a directory tree deeper than `git_check_depth`
- **THEN** the launch announces the spot where discovery stopped and the snapshot records it

#### Scenario: A worktree's common directory is covered through the worktree
- **WHEN** a session launches from a linked worktree and its common directory is mounted alongside it
- **THEN** the baseline records the worktree with its common directory's dangerous keys, hooks and worktree pointers, and the common directory root itself adds no repository entry
