## ADDED Requirements

### Requirement: Agent image includes kubectl

The agent image SHALL include a pinned, checksum-verified `kubectl` so a caged session can operate against a Kubernetes cluster (used with the kube broker source).

#### Scenario: kubectl present and pinned
- **WHEN** the agent image is built
- **THEN** `kubectl` is on PATH at the version pinned in config, installed through a checksum gate
