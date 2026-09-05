## Purpose

The semantics of the egress allowlist: how allow/block rules are evaluated, and the guarantees that evaluation is identical everywhere and cannot be bypassed by encoding tricks or broken configuration.

## ADDED Requirements

### Requirement: Policy evaluation has fixed, tested precedence

Egress decisions SHALL be evaluated in this order: host blocklist → path-level allow carve-outs → path-level blocks → configured default mode. The default mode SHALL be deny unless explicitly configured otherwise.

#### Scenario: Path carve-out on a blocked host
- **WHEN** a host is blocked but a specific path on it is allow-carved
- **THEN** requests to that path succeed and requests to any other path on that host are denied

### Requirement: Policy fails closed

A policy file that is missing, unparseable, or internally invalid SHALL cause all egress to be denied.

#### Scenario: Corrupt policy file
- **WHEN** the policy file fails to parse at proxy start or reload
- **THEN** every request is denied and the failure is loudly reported to the operator

### Requirement: One matcher, identical verdicts everywhere

Every component that evaluates policy (in-proxy addon, launcher preview, debug CLI) SHALL use the same matcher implementation, and a parity test SHALL assert identical verdicts across all call sites for a shared corpus of cases.

#### Scenario: Parity test in CI
- **WHEN** the parity suite runs the shared verdict corpus against every call site
- **THEN** all call sites return identical verdicts for every case

### Requirement: Encoding-aware asymmetric matching

Path rules SHALL normalize percent-encoding and `.`/`..` segments before matching. Block rules SHALL fire if ANY encoded/decoded form of the path matches. Allow rules — in particular carve-outs overriding a host block — SHALL fire only if ALL forms match.

#### Scenario: Encoded path targeting a blocked endpoint
- **WHEN** a request uses percent-encoding or dot-segments to disguise a path matched by a block rule
- **THEN** the block rule fires and the request is denied

#### Scenario: Encoded path widening an allow carve-out
- **WHEN** a request uses an encoded form that matches an allow carve-out only after decoding (or only before)
- **THEN** the allow rule does not fire and the request is denied

### Requirement: Harness vendor endpoints get path-level treatment

The default policy SHALL allow the harness's functionally required endpoints while denying its telemetry/phone-home endpoints, and this split SHALL be expressed as ordinary policy rules (no special-case code).

#### Scenario: Harness operates without telemetry
- **WHEN** the harness performs normal work inside the cage
- **THEN** required API calls succeed and telemetry requests are denied without breaking the harness
