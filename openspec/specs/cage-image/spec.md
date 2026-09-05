# cage-image Specification

## Purpose
The contract of the agent image: what is guaranteed about its contents, its build inputs, and its behavior at container start.

## Requirements

### Requirement: Agent runs as a non-root user

The harness process and everything it spawns SHALL run as a dedicated non-root user inside the container. The user's uid SHALL be aligned at container start to the host uid supplied by the launcher (rather than baked at build time), so one image serves any host user; when no uid is supplied the image's default non-root uid is used.

#### Scenario: Identity check at start
- **WHEN** the container starts and the harness launches
- **THEN** the effective UID is a dedicated non-root user matching the launcher-supplied host uid

#### Scenario: Home writable after uid alignment
- **WHEN** the agent uid is aligned to the host uid at start
- **THEN** the agent user owns and can write its bind-mounted home directory

### Requirement: Harness self-update is disabled

The harness inside the image SHALL NOT self-update; at most it notifies. Harness version changes SHALL happen only by image rebuild.

#### Scenario: Update availability inside a session
- **WHEN** the harness detects a newer version mid-session
- **THEN** it does not modify its own installation and the session state remains intact

### Requirement: Agent instructions are image cargo

Prompts, skills, and agent instructions SHALL be stored in the image and deployed into the harness configuration directory on every container start, overwriting mutable copies.

#### Scenario: Locally modified instruction file
- **WHEN** an instruction file in the session state was modified and the container restarts
- **THEN** the file matches the image's version after start

### Requirement: Build inputs are verified and reconstructible

Every binary/tool downloaded at build time SHALL pass a checksum or digest verification gate before use. Tool versions SHALL come from configuration (not hardcoded), with any floating version resolved to a concrete one at build time. Build-time tokens SHALL never persist in image layers. Sidecar images SHALL be pinned by digest.

#### Scenario: Tampered download
- **WHEN** a build-time download does not match its expected checksum/digest
- **THEN** the build fails before the artifact is unpacked

#### Scenario: Token leak check
- **WHEN** the built image filesystem is scanned for the build-time token value
- **THEN** no layer contains it

### Requirement: Build context is allowlisted

The build context SHALL be deny-by-default: only explicitly re-included paths (the COPY sources) enter it.

#### Scenario: State directory adjacent to the Dockerfile
- **WHEN** a state or credential file exists in the build directory but is not an explicit COPY source
- **THEN** it is absent from the build context and the image
