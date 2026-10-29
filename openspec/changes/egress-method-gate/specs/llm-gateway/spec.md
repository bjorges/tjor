# Spec Delta

## ADDED Requirements

### Requirement: Session policy augmentation derives from the validated base policy

When the gateway is enabled, the session policy SHALL be generated from the base policy as parsed and validated by the one policy parser, and SHALL re-emit every section of it, the `methods` rules included. A base policy the parser rejects SHALL fail the launch loudly with the parser's errors; it SHALL never be re-emitted without the part it could not parse.

#### Scenario: A malformed methods section fails the launch
- **WHEN** the gateway is enabled and the base policy has a `[[methods.restrict]]` rule with a misspelled key
- **THEN** the launch stops with the parser's error, and no session policy is written

#### Scenario: Method rules survive augmentation
- **WHEN** the gateway is enabled and the base policy restricts a host to `GET` with a `POST` exception on one path
- **THEN** the session policy denies `POST` to that host with `method-block:POST`, admits the excepted path, and still carves the gateway's inference paths

### Requirement: Inference paths stay reachable under method restrictions

The augmentation SHALL add a `[[methods.except]]` rule admitting `POST` on each of the gateway's POST inference paths for the gateway host, so a restrict rule that matches the gateway host (for example `host = "*"`) cannot deny inference. The management surface SHALL stay denied by the host block regardless.

#### Scenario: A wildcard restriction does not break inference
- **WHEN** the base policy restricts `*` to `GET` and the gateway is enabled
- **THEN** `POST /v1/chat/completions` toward the gateway host is allowed by its carve-out and `POST /key/generate` is denied with `host-block`
