# Spec Delta

## Purpose

Detects, without preventing, git metadata written inside the cage that would run code in the operator's host git: a baseline of every writable repository at launch, a diff at exit, teardown and on demand, and a pending marker that survives crashes so an unchecked repository is never silent.

## ADDED Requirements

### Requirement: A launch records a git-metadata baseline out of the agent's reach

At launch, once the mount set is final, the launcher SHALL record for every git directory discovered under a writable mount root: the dangerous configuration keys present and their values (the documented set covering hooks, editors and pagers, ssh and credential commands, filter, diff and merge drivers, shell aliases, includes, remote helpers and proxies, URL rewrites, `safe.*` and `extensions.*`), whether the config file is a symbolic link, every worktree pointer (`.git` files and `worktrees/*/gitdir`, `commondir`), a hash of every hook file, and the nested repositories already present in the working tree. The baseline and a pending-check marker SHALL be stored under the session state directory, outside every path mounted into the cage. The launch SHALL announce the number of repositories baselined.

#### Scenario: Baseline covers every writable root
- **WHEN** a session launches with a workspace and a `--dir` repository, one of them holding a nested repository
- **THEN** the baseline holds an entry for each of the three git directories and the pending marker exists before the agent starts

### Requirement: A check reports cage-written metadata that host git would run

A check SHALL re-snapshot the baseline's repositories and report, per repository, escape-sanitized: a dangerous key added, changed or removed with its old and new value; an include added; a config file that became a symbolic link; a worktree pointer that changed or a worktree that appeared; a hook file added or changed; a nested repository that appeared; a baseline repository that vanished. Writes to keys outside the dangerous set — `branch.*`, `remote.*.url`, `remote.*.fetch`, `remote.*.push`, `user.*` — SHALL NOT be findings.

#### Scenario: Planted patterns are reported
- **WHEN** after the baseline the cage sets `core.hooksPath`, adds an `include.path`, replaces `.git/config` with a symlink, re-points a worktree's `.git` file, and creates `src/.git`
- **THEN** the check reports each with the repository, the class, the key or path, and old and new values where they exist

#### Scenario: A push -u is not a finding
- **WHEN** after the baseline the repository gains `branch.main.remote`, `branch.main.merge` and `remote.origin.url`
- **THEN** the check is clean

### Requirement: The check runs at exit, at teardown and on demand; the marker clears only when clean

The launcher SHALL run the check when an attached session's harness exits, at `tjor down`, and on demand via `tjor git-check [<repo> | --session <id>] [--ack] [--json]`. `tjor git-check <repo>` SHALL locate every session baseline that covers that repository; with no argument it SHALL use the current workspace's session. The pending marker SHALL be cleared only by a clean check or by an explicit `--ack`; a check with findings SHALL set it (creating it when absent) and say so. `--ack` SHALL accept the current state as the new baseline, so acknowledged findings are not reported again while anything written afterwards is. `tjor git-check` SHALL exit non-zero when findings exist (and zero after `--ack`), so it can serve as a pre-use gate in the operator's own shell; tjor SHALL NOT install such a hook itself. Teardown SHALL still complete when findings exist.

#### Scenario: Findings keep the marker
- **WHEN** `tjor git-check --session <id>` finds a dangerous key
- **THEN** it prints the finding, exits non-zero, and the marker remains

#### Scenario: Acknowledge clears the marker and re-baselines
- **WHEN** `tjor git-check --session <id> --ack` is run after findings
- **THEN** the marker is removed, the command exits zero, the next check is clean, and a dangerous key written after the acknowledgement is reported again

#### Scenario: Clean check clears the marker
- **WHEN** a check finds nothing
- **THEN** the marker is removed

### Requirement: Unchecked sessions are surfaced

`tjor ls` SHALL list every session whose pending marker exists — including sessions with no running containers, such as one killed with `SIGKILL` — naming the repositories and the command that clears it.

#### Scenario: A killed session stays visible
- **WHEN** a session's containers are removed without a teardown check
- **THEN** `tjor ls` reports the session as unchecked until `tjor git-check` clears or acknowledges it
