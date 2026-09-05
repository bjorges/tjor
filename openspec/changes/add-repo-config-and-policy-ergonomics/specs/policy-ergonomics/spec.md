## Purpose

Make egress denials legible and the allowlist easy to grow, so the most likely first-hour frustration — a blocked request with no obvious fix — becomes a one-command widening.

## ADDED Requirements

### Requirement: Explain a policy verdict

`tjor policy <url> --explain` SHALL report the verdict, the deciding stage/rule, and the pattern that matched (when one did), for the active policy.

#### Scenario: Explain a denial
- **WHEN** `tjor policy https://blocked.example/ --explain` runs and the host is not allowed
- **THEN** the output states DENY, the deciding rule (e.g. default-deny or a block rule), and any matching pattern

### Requirement: Add a host to the active policy

`tjor policy add <host>` SHALL append the host to the allow list of the active policy file (the repo policy when trusted and in effect, else the user policy, creating the user policy if absent), and the change SHALL take effect on the next launch.

#### Scenario: Widen after a denial
- **WHEN** a host was denied and the user runs `tjor policy add that.host`
- **THEN** the host is added to the active allow list and a subsequent `tjor policy https://that.host/` allows it

### Requirement: Session denial log

The proxy SHALL record each denied egress decision (host, deciding rule, timestamp) to a denial log in the session state, and `tjor denials [session]` SHALL display it. The log SHALL be readable while the session runs.

#### Scenario: See what got blocked
- **WHEN** a caged agent's requests are denied and `tjor denials` is run for that session
- **THEN** the denied hosts and their deciding rules are listed, so the user can `tjor policy add` them

#### Scenario: No denials
- **WHEN** a session has had no denied egress
- **THEN** `tjor denials` reports none
