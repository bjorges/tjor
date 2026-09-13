# cage-image Delta

## ADDED Requirements

### Requirement: Agent image includes the kernel-sandbox tool

The agent image SHALL include a pinned, checksum-verified `cplt` binary so the entrypoint can enforce the kernel-sandbox tier. The version SHALL come from configuration (not hardcoded in the Dockerfile) and the download SHALL pass the same per-arch sha256 gate as every other build-time binary.

#### Scenario: cplt present and pinned
- **WHEN** the agent image is built
- **THEN** `cplt` is on PATH at the version pinned in config, installed through a checksum gate

#### Scenario: Tampered cplt download
- **WHEN** the downloaded cplt release asset does not match its pinned sha256
- **THEN** the build fails before the artifact is unpacked
