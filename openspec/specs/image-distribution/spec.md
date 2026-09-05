# image-distribution Specification

## Purpose
Prebuilt, uid-agnostic, multi-arch agent images published to a registry, so `tjor run` pulls instead of building on first use — while staying reproducible from the pinned tool versions.

## Requirements

### Requirement: Agent images are uid-agnostic

A published or locally-built agent image SHALL NOT bake the host user's uid. At container start the entrypoint SHALL align the `agent` user to the uid supplied by the launcher (`$(id -u)` on the host) and ensure the agent user owns its home, before dropping privileges.

#### Scenario: Same image, different host uids
- **WHEN** the same agent image is run by two host users with different uids
- **THEN** each session's agent runs as that host's uid and can write its bind-mounted home, with no per-user rebuild

### Requirement: Published images are versioned and multi-arch

The project SHALL publish each harness's agent image (and the proxy/conformance images) to a registry, built for both `linux/amd64` and `linux/arm64`, tagged by the tjor release version, with a moving `latest` tag.

#### Scenario: Pull matches the platform
- **WHEN** a user on either architecture pulls the published image for a version
- **THEN** the correct per-arch image is retrieved

### Requirement: Launcher prefers a published image, falls back to build

With a published registry configured (the default), `tjor run` SHALL use the published image for the running tjor version when it can be pulled, and SHALL otherwise build locally (today's behavior). `tjor build` SHALL always build locally.

#### Scenario: Published image available
- **WHEN** a published image for the current version exists and is reachable
- **THEN** `tjor run` pulls and uses it instead of building

#### Scenario: No published image reachable
- **WHEN** no published image can be pulled (offline, unpublished dev version, private)
- **THEN** `tjor run` builds the image locally and proceeds

### Requirement: Published images stay reproducible from pins

A published image SHALL be built from the same pinned tool versions and checksums in `config/tjor.toml` that a local build uses; the registry is a cache of that build, not an independent source of truth.

#### Scenario: Rebuild from pins matches
- **WHEN** the published image and a local build use the same config pins
- **THEN** they install the same tool versions (verified by the checksum gates)
