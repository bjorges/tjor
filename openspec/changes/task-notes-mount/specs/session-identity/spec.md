# Spec Delta

## MODIFIED Requirements

### Requirement: Host paths never leave the cage in full

Identity values derived from host filesystem paths (`TJOR_WORKTREE`) SHALL carry only the path's basename on the wire; the full path reveals the host OS username and directory layout and remains available only as environment inside the cage. `TJOR_TASK_DIR`, the task's notes directory, SHALL have no wire form at all: it is environment inside the cage only, and the identity set carries no header for it.

#### Scenario: Worktree attribution without path leakage
- **WHEN** a session launched from `/Users/alice/git/myrepo/wt-1` injects identity toward an `inject_hosts` destination
- **THEN** `x-agent-worktree` carries `wt-1`, not the full host path

#### Scenario: The notes directory has no header
- **WHEN** a session with `TJOR_TASK_DIR=/Users/alice/scratch/tasks/A` injects identity toward an `inject_hosts` destination
- **THEN** no `x-agent-*` header names the directory or its basename, and a forged `x-agent-task-dir` header is stripped like any unknown identity header
