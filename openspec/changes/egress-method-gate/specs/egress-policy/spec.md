# Spec Delta

## MODIFIED Requirements

### Requirement: Policy evaluation has fixed, tested precedence

Egress decisions SHALL be evaluated in this order: host blocklist → path-level allow carve-outs → path-level blocks → method gate → configured default mode. The default mode SHALL be deny unless explicitly configured otherwise. The method gate SHALL be consulted for every request the earlier stages did not deny, a carved-out request included, and SHALL only ever deny: a request it admits is decided by the remaining stages exactly as it would be without a `methods` section.

#### Scenario: Path carve-out on a blocked host
- **WHEN** a host is blocked but a specific path on it is allow-carved
- **THEN** requests to that path succeed and requests to any other path on that host are denied

#### Scenario: The method gate never widens a verdict
- **WHEN** the same request is evaluated against a policy and against that policy with its `methods` section removed
- **THEN** either both verdicts are identical, or the policy with the section denies with a method rule where the other allows; no other difference exists

#### Scenario: A carved-out path is still gated by method
- **WHEN** a host is blocked, a path on it is allow-carved, and the host is method-restricted to GET
- **THEN** a GET to the carved path is allowed by the carve-out and a POST to it is denied by the method gate

### Requirement: Policy fails closed

A policy file that is missing, unparseable, or internally invalid SHALL cause all egress to be denied.

#### Scenario: Corrupt policy file
- **WHEN** the policy file fails to parse at proxy start or reload
- **THEN** every request is denied and the failure is loudly reported to the operator

#### Scenario: Malformed methods section
- **WHEN** the `methods` section has an unknown key, a rule with a missing or mistyped field, or a method name that is not one to sixteen upper-case letters
- **THEN** the whole policy is invalid and every request, on every host, is denied

### Requirement: One matcher, identical verdicts everywhere

Every component that evaluates policy (in-proxy addon, launcher preview, debug CLI) SHALL use the same matcher implementation, and a parity test SHALL assert identical verdicts across all call sites for a shared corpus of cases. Each corpus case SHALL carry the request method, and every call site SHALL receive it: no call site evaluates a request without its method.

#### Scenario: Parity test in CI
- **WHEN** the parity suite runs the shared verdict corpus against every call site
- **THEN** all call sites return identical verdicts for every case

#### Scenario: Method cases are part of the corpus
- **WHEN** the corpus contains a request denied only because of its method
- **THEN** the proxy addon, the launcher preview and the CLI all return that method denial, with the same rule

## ADDED Requirements

### Requirement: A method restriction denies unlisted methods on a host

A `[[methods.restrict]]` rule names a host pattern and the methods allowed on it. A request to a host matched by any restrict rule SHALL be denied when its method is not listed by every restrict rule matching that host, unless a method exception admits it. The denial SHALL name the method in its rule (`method-block:<METHOD>`) and the restrict rule's host pattern. Hosts no restrict rule matches are not affected.

#### Scenario: POST to a read-only host
- **WHEN** `api.example.test` is restricted to `GET` and `HEAD` and the agent sends a POST to any path on it
- **THEN** the request is denied with rule `method-block:POST`

#### Scenario: GET to a read-only host
- **WHEN** `api.example.test` is restricted to `GET` and `HEAD` and the agent sends a GET to a path the other stages allow
- **THEN** the request is allowed, by the same stage and rule as without the restriction

#### Scenario: Two restrictions on one host intersect
- **WHEN** `*.example.test` is restricted to `GET` and `api.example.test` is restricted to `GET` and `POST`
- **THEN** a POST to `api.example.test` is denied, because one matching restriction does not list it

#### Scenario: A restriction cannot allow what another stage denies
- **WHEN** a host is restricted to `GET` and a path on it is matched by a path block
- **THEN** a GET to that path is denied by the path block, as before

### Requirement: A method exception admits a listed method on an exact path

A `[[methods.except]]` rule names a host pattern, a path pattern and the methods it admits. It SHALL lift a method denial only when the host matches, the method is listed, and every encoded and decoded form of the request path matches the path pattern (the allow-side asymmetry of charter L22). An admitted request SHALL continue to the default-mode stage; an exception never allows on its own and never affects a host without a restriction.

#### Scenario: Search by POST on a read-only host
- **WHEN** `api.example.test` is restricted to `GET` and an exception admits `POST` on `/rest/api/*/search*`
- **THEN** `POST /rest/api/2/search?jql=…` is allowed and `POST /rest/api/2/issue` is denied with `method-block:POST`

#### Scenario: Encoding cannot widen an exception
- **WHEN** the agent sends `POST /rest/api/2/%73earch` or `POST /rest/api/2/search/../issue` against that policy
- **THEN** the exception does not apply and the request is denied with `method-block:POST`

#### Scenario: An exception does not bypass the default mode
- **WHEN** an exception admits `POST` on a path of a host that is neither allow-listed nor carved out in strict-allow mode
- **THEN** the request is denied by the default mode

### Requirement: The request method is validated before any rule is consulted

The method SHALL be upper-cased and SHALL match `^[A-Z]{1,16}$`; a request whose method does not is denied with a fail-closed rule regardless of policy. CONNECT SHALL be decided on the host alone, as before, because the method travels inside the tunnel; the inner request is evaluated with its own method once the tunnel is open.

#### Scenario: Lower-case method is normalised
- **WHEN** the agent sends `post` to a host restricted to `GET`
- **THEN** it is evaluated as `POST` and denied with `method-block:POST`

#### Scenario: Malformed method
- **WHEN** a request's method contains characters outside upper-case letters after normalisation, or is longer than sixteen characters
- **THEN** it is denied with `fail-closed:bad-method`, on any host

#### Scenario: CONNECT is unchanged
- **WHEN** the agent opens a CONNECT tunnel to a host that is allow-listed and method-restricted
- **THEN** the tunnel is opened on the host decision alone and each request inside it is evaluated with its method
