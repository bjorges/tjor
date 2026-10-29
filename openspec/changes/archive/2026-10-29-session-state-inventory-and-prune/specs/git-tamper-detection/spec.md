# Spec Delta

## MODIFIED Requirements

### Requirement: The check runs at exit, at teardown and on demand; the marker clears only when clean or acknowledged

The launcher SHALL run the check when an attached session's harness exits, at `tjor down`, and on demand via `tjor git-check [<repo> | --session <id>] [--ack [<token>]] [--json]`. `tjor git-check <repo>` SHALL locate every session baseline that covers that repository; with no argument it SHALL use the current workspace's session. The pending marker SHALL be cleared only by a clean check or by an acknowledgement; a check with findings — on the human path and on `--json` alike — SHALL set it (creating it when absent) and say so. Findings SHALL be printed with a token that names exactly that set of findings; `--ack <token>` SHALL accept the current state as the new baseline only when the token matches the current findings, so acknowledged findings are not reported again while anything written afterwards is. A bare `--ack` while findings exist, a wrong token, or a stale token (the state changed since it was issued) SHALL show the findings and the current token and refuse. `tjor git-check` SHALL exit non-zero when findings exist or an acknowledgement is refused, and zero after an accepted acknowledgement, so it can serve as a pre-use gate in the operator's own shell; tjor SHALL NOT install such a hook itself. `--json` output SHALL be an object carrying the findings, the token and the incomplete spots, sanitized like the terminal output. Teardown SHALL still complete when findings exist.

Exactly one other path removes a pending marker: `tjor prune --session <id> --discard-unreviewed` deletes the session's whole state directory — baseline and marker together — and SHALL say that unreviewed findings were discarded. An age-based prune, a credential-only prune, `tjor reset` of any tier below `all`, and every other command SHALL leave a pending marker and its baseline in place.

#### Scenario: Findings keep the marker
- **WHEN** `tjor git-check --session <id>` finds a dangerous key
- **THEN** it prints the finding and a token, exits non-zero, and the marker remains

#### Scenario: A bare acknowledgement with findings is refused
- **WHEN** `tjor git-check --session <id> --ack` is run while findings exist
- **THEN** the findings and the token are shown, the command exits non-zero, and the marker remains

#### Scenario: Acknowledge with the token clears the marker and re-baselines
- **WHEN** `tjor git-check --session <id> --ack <token>` is run with the token of the findings last shown
- **THEN** the marker is removed, the command exits zero, the next check is clean, and a dangerous key written after the acknowledgement is reported again with a new token

#### Scenario: A stale token is refused
- **WHEN** the state changes after a token was issued and `--ack` is run with the old token
- **THEN** the findings and the current token are shown and the command exits non-zero

#### Scenario: Clean check clears the marker
- **WHEN** a check finds nothing
- **THEN** the marker is removed

#### Scenario: Only an explicit per-session prune discards a pending marker
- **WHEN** a session's marker is pending and it has no container
- **THEN** `tjor prune --older-than 0d` and `tjor prune --session <id> --creds-only` leave the baseline and the marker in place, and `tjor prune --session <id> --discard-unreviewed` removes the directory and reports that unreviewed findings were discarded
