# Spec Delta

## MODIFIED Requirements

### Requirement: Explain a policy verdict

`tjor policy <url> [--method <M>] --explain` SHALL report the verdict, the deciding stage/rule, and the pattern that matched (when one did), for the active policy. The method defaults to `GET` when not given, so a URL alone previews a read; `--method` previews any other method the same way the proxy would decide it.

#### Scenario: Explain a denial
- **WHEN** `tjor policy https://blocked.example/ --explain` runs and the host is not allowed
- **THEN** the output states DENY, the deciding rule (e.g. default-deny or a block rule), and any matching pattern

#### Scenario: Preview a method denial
- **WHEN** `tjor policy https://api.example.test/x --method POST` runs and the host is restricted to GET
- **THEN** the output states DENY with rule `method-block:POST` and the restricting host pattern, while the same command without `--method` states ALLOW

### Requirement: Session denial log

The proxy SHALL record each denied egress decision (host, deciding rule, timestamp) to a denial log in the session state, and `tjor denials [session]` SHALL display it. The log SHALL be readable while the session runs. For a denial by the method gate the deciding rule SHALL carry the refused method (`method-block:<METHOD>`), so the operator can tell a refused write from a blocked host.

#### Scenario: See what got blocked
- **WHEN** a caged agent's requests are denied and `tjor denials` is run for that session
- **THEN** the denied hosts and their deciding rules are listed, so the user can `tjor policy add` them

#### Scenario: No denials
- **WHEN** a session has had no denied egress
- **THEN** `tjor denials` reports none

#### Scenario: A refused method is visible
- **WHEN** the agent's POST to a read-only host was denied and `tjor denials` is run
- **THEN** the line for that host shows `method-block:POST` as the rule
