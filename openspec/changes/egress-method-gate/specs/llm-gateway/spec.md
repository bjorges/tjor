# Spec Delta

## ADDED Requirements

### Requirement: Session policy augmentation derives from the validated base policy

When the gateway is enabled, the session policy SHALL be generated from the base policy as parsed and validated by the one policy parser, re-emitting every section, the `methods` rules included. A base policy the parser rejects SHALL fail the launch with the parser's errors: no session policy is written, one left by an earlier launch into the same directory is removed, no agent starts, and the launcher says what that means for sidecars still running from an earlier launch.

#### Scenario: A malformed methods section fails the launch
- **WHEN** the gateway is enabled and the base policy has a `[[methods.restrict]]` rule with a misspelled key
- **THEN** the launch stops with the parser's error, and no session policy file exists in the session directory

#### Scenario: A reused session directory does not keep a stale policy
- **WHEN** the session directory holds a session policy from an earlier launch and the base policy is now rejected by the parser
- **THEN** the launch stops with the parser's error, the stale session policy is removed, no agent starts, and the output names the running-sidecar consequence

#### Scenario: Method rules survive augmentation
- **WHEN** the gateway is enabled and the base policy restricts a host to `GET` with a `POST` exception on one path
- **THEN** the session policy denies `POST` to that host with `method-block:POST`, admits the excepted path, and still carves the gateway's inference paths

#### Scenario: The launcher path is tested
- **WHEN** the launcher's topology step runs against a malformed base policy with the gateway enabled, in a fresh session directory and in one seeded with a stale session policy
- **THEN** the integration test sees a non-zero exit, the parser's error on stderr, and no session policy file in either case

### Requirement: Inference paths stay reachable under method restrictions

The augmentation SHALL add a `[[methods.except]]` rule admitting `POST` on each of the gateway's POST inference paths for the gateway host, so a restrict rule that matches the gateway host (for example `host = "*"`) cannot deny inference. The management surface SHALL stay denied by the host block regardless.

#### Scenario: A wildcard restriction does not break inference
- **WHEN** the base policy restricts `*` to `GET` and the gateway is enabled
- **THEN** `POST /v1/chat/completions` toward the gateway host is allowed by its carve-out and `POST /key/generate` is denied with `host-block`
