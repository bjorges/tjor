# Spec Delta

## MODIFIED Requirements

### Requirement: Host paths never leave the cage in full

Identity values derived from host filesystem paths (`TJOR_WORKTREE`) SHALL carry only the path's basename on the wire; the full path reveals the host OS username and directory layout and remains available only as environment inside the cage. No identity header SHALL be derived from `TJOR_TASK_DIR`, the task's notes directory; the task id, which is that directory's basename by construction, travels as `x-agent-task-id` as today.

#### Scenario: Worktree attribution without path leakage
- **WHEN** a session launched from `/Users/alice/git/myrepo/wt-1` injects identity toward an `inject_hosts` destination
- **THEN** `x-agent-worktree` carries `wt-1`, not the full host path

#### Scenario: No header derived from the notes directory
- **WHEN** a session with `TJOR_TASK_DIR=/Users/alice/scratch/tasks/a` injects identity toward an `inject_hosts` destination
- **THEN** `x-agent-task-id` carries `a`, no header carries the directory's path, and a forged `x-agent-task-dir` header is stripped like any unknown identity header
