# policy-ergonomics Specification

## Purpose
Make egress denials legible and the allowlist easy to grow, so the most likely first-hour frustration — a blocked request with no obvious fix — becomes a one-command widening.

## Requirements

### Requirement: Explain a policy verdict

`tjor policy <url> [--method <M>] --explain` SHALL report the verdict, the deciding stage/rule, and the pattern that matched (when one did), for the active policy. The method defaults to `GET`; `--method <M>` (or `--method=<M>`) previews any other method as typed. On a method-restricted host the output SHALL note that the proxy refuses protocol switches and method-override headers on that host, unseen by the preview: prose in text mode, a boolean field under `--json`.

#### Scenario: Explain a denial
- **WHEN** `tjor policy https://blocked.example/ --explain` runs and the host is not allowed
- **THEN** the output states DENY, the deciding rule (e.g. default-deny or a block rule), and any matching pattern

#### Scenario: Preview a method denial
- **WHEN** `tjor policy https://api.example.test/x --method POST` runs and the host is restricted to GET
- **THEN** the output states DENY with rule `method-block:POST` and the restricting host pattern, while the same command without `--method` states ALLOW

#### Scenario: Explain a verdict on a restricted host
- **WHEN** `tjor policy https://api.example.test/ws --explain` runs and the host is restricted to GET
- **THEN** the output states ALLOW and notes that the proxy refuses protocol switches and method-override headers on this host, and the same command for an unrestricted host prints no such note

#### Scenario: The note never breaks JSON output
- **WHEN** `tjor policy https://api.example.test/ws --json` runs and the host is restricted to GET
- **THEN** the output is a single JSON object carrying `"header_guards": true` and no prose line

### Requirement: Add a host to the active policy

`tjor policy add <host>` SHALL append the host to the allow list of the active policy file (the repo policy when trusted and in effect, else the user policy, creating the user policy if absent), and the change SHALL take effect on the next launch. The insertion SHALL land in the `[hosts]` table's `allow` list only, never in the `allow` list of a `[[methods.restrict]]` rule, and SHALL create that list when the table has none.

#### Scenario: Widen after a denial
- **WHEN** a host was denied and the user runs `tjor policy add that.host`
- **THEN** the host is added to the active allow list and a subsequent `tjor policy https://that.host/` allows it

#### Scenario: A method rule's allow list is never the insertion point
- **WHEN** the active policy's `[hosts]` table has no `allow` list and is followed by a `[[methods.restrict]]` rule
- **THEN** `tjor policy add that.host` creates `hosts.allow` with the host and leaves the restrict rule unchanged

### Requirement: Session denial log

The proxy SHALL record each denied egress decision (host, deciding rule, timestamp) to a denial log in the session state, and `tjor denials [session]` SHALL display it. The log SHALL be readable while the session runs. A method-gate denial SHALL carry the refused method (`method-block:<METHOD>`) and a header-guard denial its guard (`header-block:<guard>`); per kind present, `tjor denials` SHALL print the hint in the scenarios below, never `tjor policy add`.

#### Scenario: See what got blocked
- **WHEN** a caged agent's requests are denied and `tjor denials` is run for that session
- **THEN** the denied hosts and their deciding rules are listed, so the user can `tjor policy add` them

#### Scenario: No denials
- **WHEN** a session has had no denied egress
- **THEN** `tjor denials` reports none

#### Scenario: A refused method is visible
- **WHEN** the agent's POST to a read-only host was denied and `tjor denials` is run
- **THEN** the line for that host shows `method-block:POST` as the rule and the output names `[[methods.except]]` or the restriction's `allow` list as the way to widen it

#### Scenario: A non-standard method token gets no policy hint
- **WHEN** the agent sent `get` to a read-only host and `tjor denials` is run
- **THEN** the line shows `method-block:get` and the output says the client sent a non-standard method token that no policy rule can name, so the client is what to fix

#### Scenario: A refused header is visible
- **WHEN** the agent's WebSocket handshake to a read-only host was denied and `tjor denials` is run
- **THEN** the line shows `header-block:upgrade` and the output says the host must be left unrestricted to admit it, not that an exception would

### Requirement: Teardown surfaces a denial recap

`tjor down` SHALL print a short recap of denied egress when the session's denial log is non-empty: the total, the most-denied hosts with counts, how to review (`tjor denials`) and widen (`tjor policy add <host>`), and, per kind of `method-block:` or `header-block:` line present, its count and its hint (scenario below). With no denials, teardown SHALL stay quiet (no recap noise). Denied hostnames are attacker-influenced and SHALL be rendered through the shared terminal-escape sanitizer.

#### Scenario: Blocked session is surfaced at teardown
- **WHEN** a session recorded denied egress and `tjor down` tears it down
- **THEN** the teardown output states the denial count and top denied hosts, and names the review/widen commands

#### Scenario: Clean session tears down quietly
- **WHEN** a session recorded no denials
- **THEN** `tjor down` prints no denial recap

#### Scenario: Hostile hostname cannot inject terminal escapes
- **WHEN** a denied hostname contains terminal-control bytes
- **THEN** the recap renders them as visible tokens, never raw control sequences

#### Scenario: Method and header denials get their own hints
- **WHEN** a session recorded denials by the method gate, by a non-standard method token and by a header guard, and `tjor down` tears it down
- **THEN** the recap states how many were refused by each, points at `[[methods.except]]` for the first, at the client for the second, and says the third has no exception
