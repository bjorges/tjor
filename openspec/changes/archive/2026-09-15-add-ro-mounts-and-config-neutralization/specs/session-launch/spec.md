## ADDED Requirements

### Requirement: Read-only additional repositories via repeatable --dir-ro

`tjor run` SHALL accept a repeatable `--dir-ro <path>` option. Each given path
SHALL be resolved to an absolute path and mounted into the agent container at
that same absolute path **read-only**, enforced at the container level so no
process in the container — the harness tree and `docker exec` alike — can
write, create, delete, or rename anything under it. A `--dir-ro` mount SHALL
otherwise be treated as a mounted repo: trusted by git (`safe.directory`) and
covered by launch-time secret masking (dotenv discovery and configured deny
paths/dirs). The sensitive-host-path refusal SHALL apply to `--dir-ro` exactly
as to `--dir` (read-only access still exposes content for exfiltration), with
the same `--unsafe-dir` override. The same path given to both `--dir` and
`--dir-ro` in one invocation SHALL abort the launch with a clear error rather
than silently picking a writability.

#### Scenario: Writes into a read-only mount are refused

- **WHEN** a session is launched with `--dir-ro /path/to/repo-b` and any
  process inside the container attempts to create, modify, delete, or rename
  a file under `/path/to/repo-b`
- **THEN** the operation fails, while reads of the same tree succeed

#### Scenario: Git works read-only in the mount

- **WHEN** the agent runs read-only git operations (`status`, `log`, `diff`)
  inside a `--dir-ro` mounted repository
- **THEN** they succeed without dubious-ownership refusals

#### Scenario: Secret masking still covers the read-only mount

- **WHEN** a `--dir-ro` mounted repo contains a `.env` file at launch
- **THEN** the file is masked exactly as it would be in a writable mount

#### Scenario: Sensitive path refused read-only too

- **WHEN** `tjor run --dir-ro <sensitive path>` names a refused host location
  (home root, credential dirs) without `--unsafe-dir`
- **THEN** the launch aborts with an error stating the read-only exposure risk

#### Scenario: Conflicting writability for one path

- **WHEN** one invocation passes the same resolved path to both `--dir` and
  `--dir-ro`
- **THEN** the launch aborts with an error naming the path and the conflict

## MODIFIED Requirements

### Requirement: Each extra dir is verified before mounting

Every `--dir` and `--dir-ro` path SHALL be verified to exist and to be shared
with the container runtime (the same VM-share check applied to the primary
workspace). A missing or unshared path SHALL abort the launch with a clear
error naming the path.

#### Scenario: Unshared extra dir

- **WHEN** a `--dir` or `--dir-ro` path is not shared with the Docker VM
  (bind mounts of it would appear empty)
- **THEN** the launch aborts, naming the path, before the agent starts

#### Scenario: Nonexistent extra dir

- **WHEN** a `--dir` or `--dir-ro` path does not exist
- **THEN** the launch aborts with an error naming the path
