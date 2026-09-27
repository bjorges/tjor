# Spec Delta

## MODIFIED Requirements

### Requirement: Launcher prefers a published image, falls back to build

With a published registry configured (the default), `tjor run` from an **installed release** SHALL use the published image for the running tjor version when it can be pulled, and SHALL otherwise build locally. A **source tree** — a git checkout, or a self-installed tree carrying the `.tjor-source-sha` marker — SHALL always build locally and SHALL NOT pull, regardless of the registry setting (ADR 0008: the security-conscious path is never silently replaced by a pull). `tjor build` SHALL always build locally.

#### Scenario: Published image available
- **WHEN** a published image for the current version exists and is reachable
- **THEN** `tjor run` pulls and uses it instead of building

#### Scenario: No published image reachable
- **WHEN** no published image can be pulled (offline, unpublished dev version, private)
- **THEN** `tjor run` builds the image locally and proceeds

#### Scenario: Source tree never pulls
- **WHEN** `tjor run` is invoked from a git checkout or a self-installed tree
- **THEN** the image is built locally from that tree and no registry pull is attempted
