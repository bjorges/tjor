## MODIFIED Requirements

### Requirement: Agent runs as a non-root user

The harness process and everything it spawns SHALL run as a dedicated non-root user inside the container. The user's uid SHALL be aligned at container start to the host uid supplied by the launcher (rather than baked at build time), so one image serves any host user; when no uid is supplied the image's default non-root uid is used.

#### Scenario: Identity check at start
- **WHEN** the container starts and the harness launches
- **THEN** the effective UID is a dedicated non-root user matching the launcher-supplied host uid

#### Scenario: Home writable after uid alignment
- **WHEN** the agent uid is aligned to the host uid at start
- **THEN** the agent user owns and can write its bind-mounted home directory
