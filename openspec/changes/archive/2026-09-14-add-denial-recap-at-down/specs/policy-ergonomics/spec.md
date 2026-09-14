## ADDED Requirements

### Requirement: Teardown surfaces a denial recap

`tjor down` SHALL print a short recap of the session's denied egress when the session's denial log is non-empty: the total number of denied attempts, the most-denied hosts with counts, and how to review (`tjor denials`) and widen (`tjor policy add <host>`). When the session recorded no denials, teardown SHALL stay quiet (no recap noise). Denied hostnames are attacker-influenced and SHALL be rendered through the shared terminal-escape sanitizer.

#### Scenario: Blocked session is surfaced at teardown
- **WHEN** a session recorded denied egress and `tjor down` tears it down
- **THEN** the teardown output states the denial count and top denied hosts, and names the review/widen commands

#### Scenario: Clean session tears down quietly
- **WHEN** a session recorded no denials
- **THEN** `tjor down` prints no denial recap

#### Scenario: Hostile hostname cannot inject terminal escapes
- **WHEN** a denied hostname contains terminal-control bytes
- **THEN** the recap renders them as visible tokens, never raw control sequences
