# git-tamper-detection Specification

## Purpose
Detects, without preventing, git metadata written inside the cage that would run code in the operator's host git: a baseline of every writable repository at launch, a diff at exit, teardown and on demand, and a pending marker that survives crashes so an unchecked repository is never silent.

## Requirements

### Requirement: A launch records a git-metadata baseline out of the agent's reach

At launch, once the mount set is final, the launcher SHALL record for every git directory discovered under a writable mount root: the dangerous configuration keys present with every value of each (the documented set covering hooks, editors and pagers, ssh, credential, mail and IMAP commands, filter, diff and merge drivers, trailer and GUI tool commands, shell aliases, includes, template directories, remote helpers and proxies, URL rewrites, protocol allow-lists, `safe.*` and `extensions.*`, and a remote or submodule URL naming the `ext::` or `fd::` transport), whether the config file, the `.git` entry and the hooks directory are symbolic links, every worktree pointer (`.git` files and `worktrees/*/gitdir`, `commondir`), a hash of every hook file, and the nested repositories already present in the working tree. Discovery SHALL walk each root once, never follow symbolic links, never descend below a `.git` directory, and stop `git_check_depth` levels below a root (default 32); every spot where the walk stopped — a directory at the cap that still has subdirectories, or one that could not be read — SHALL be recorded in the snapshot and announced at launch. A config file git cannot parse SHALL be recorded as unreadable, never as having no dangerous keys. The baseline and a pending-check marker SHALL be stored under the session state directory, outside every path mounted into the cage; the marker SHALL be written atomically. The launch SHALL announce the number of repositories baselined.

#### Scenario: Baseline covers every writable root
- **WHEN** a session launches with a workspace and a `--dir` repository, one of them holding a nested repository
- **THEN** the baseline holds an entry for each of the three git directories and the pending marker exists before the agent starts

#### Scenario: A truncated walk is announced
- **WHEN** a writable root holds a directory tree deeper than `git_check_depth`
- **THEN** the launch announces the spot where discovery stopped and the snapshot records it

### Requirement: A check reports cage-written metadata that host git would run, and fails closed where it cannot look

A check SHALL re-snapshot the baseline's repositories and report, per repository, escape-sanitized and with credentials embedded in URL-shaped keys or values redacted: a dangerous key added, changed or removed with its old and new values; an include added; a config file, `.git` entry or hooks directory that became a symbolic link; a worktree pointer that changed or a worktree that appeared; a hook file added or changed; a nested repository that appeared; a repository that appeared under a root that was not itself a repository; a baseline repository that vanished. It SHALL also report, as findings, a config file git cannot parse (at every check, saying whether it was already unreadable at baseline) and every spot where the walk stopped that was not recorded at baseline. Writes to keys outside the dangerous set — `branch.*`, an https or ssh `remote.*.url`, `remote.*.fetch`, `remote.*.push`, `user.*` — SHALL NOT be findings. A spot already truncated at baseline SHALL NOT be re-reported; the documentation SHALL state that a repository planted below such a spot is invisible to the check.

#### Scenario: Planted patterns are reported
- **WHEN** after the baseline the cage sets `core.hooksPath`, adds an `include.path`, replaces `.git/config` with a symlink, re-points a worktree's `.git` file, and creates `src/.git`
- **THEN** the check reports each with the repository, the class, the key or path, and old and new values where they exist

#### Scenario: An ext:: remote is a finding
- **WHEN** after the baseline the cage sets `remote.evil.url` to `ext::sh -c …`
- **THEN** the check reports a dangerous key for `remote.evil.url`

#### Scenario: A push -u is not a finding
- **WHEN** after the baseline the repository gains `branch.main.remote`, `branch.main.merge` and an https `remote.origin.url`
- **THEN** the check is clean

#### Scenario: An unparseable config is a finding
- **WHEN** after the baseline `.git/config` is corrupted so that git cannot parse it
- **THEN** the check reports the config as unreadable, with git's error, and exits non-zero

#### Scenario: A new truncation is a finding
- **WHEN** after the baseline the cage creates a directory tree deeper than `git_check_depth`
- **THEN** the check reports the spot where discovery stopped as unchecked

### Requirement: The check runs at exit, at teardown and on demand; the marker clears only when clean or acknowledged

The launcher SHALL run the check when an attached session's harness exits, at `tjor down`, and on demand via `tjor git-check [<repo> | --session <id>] [--ack [<token>]] [--json]`. `tjor git-check <repo>` SHALL locate every session baseline that covers that repository; with no argument it SHALL use the current workspace's session. The pending marker SHALL be cleared only by a clean check or by an acknowledgement; a check with findings — on the human path and on `--json` alike — SHALL set it (creating it when absent) and say so. Findings SHALL be printed with a token that names exactly that set of findings; `--ack <token>` SHALL accept the current state as the new baseline only when the token matches the current findings, so acknowledged findings are not reported again while anything written afterwards is. A bare `--ack` while findings exist, a wrong token, or a stale token (the state changed since it was issued) SHALL show the findings and the current token and refuse. `tjor git-check` SHALL exit non-zero when findings exist or an acknowledgement is refused, and zero after an accepted acknowledgement, so it can serve as a pre-use gate in the operator's own shell; tjor SHALL NOT install such a hook itself. `--json` output SHALL be an object carrying the findings, the token and the incomplete spots, sanitized like the terminal output. Teardown SHALL still complete when findings exist.

#### Scenario: Findings keep the marker
- **WHEN** `tjor git-check --session <id>` finds a dangerous key
- **THEN** it prints the finding and a token, exits non-zero, and the marker remains

#### Scenario: A bare acknowledgement with findings is refused
- **WHEN** `tjor git-check --session <id> --ack` is run while findings exist
- **THEN** the findings and the token are shown, the command exits non-zero, and the marker remains

#### Scenario: Acknowledge with the token clears the marker and re-baselines
- **WHEN** `tjor git-check --session <id> --ack <token>` is run with the token of the findings last shown
- **THEN** the marker is removed, the command exits zero, the next check is clean, and a dangerous key written after the acknowledgement is reported again with a new token

#### Scenario: A stale token is refused
- **WHEN** the state changes after a token was issued and `--ack` is run with the old token
- **THEN** the findings and the current token are shown and the command exits non-zero

#### Scenario: Clean check clears the marker
- **WHEN** a check finds nothing
- **THEN** the marker is removed

### Requirement: Unchecked sessions are surfaced

`tjor ls` SHALL list every session whose pending marker exists — including sessions with no running containers, such as one killed with `SIGKILL` — naming the repositories and the command that clears it.

#### Scenario: A killed session stays visible
- **WHEN** a session's containers are removed without a teardown check
- **THEN** `tjor ls` reports the session as unchecked until `tjor git-check` clears or acknowledges it
