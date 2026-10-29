# Spec Delta

## MODIFIED Requirements

### Requirement: Policy evaluation has fixed, tested precedence

Egress decisions SHALL be evaluated in this order: host blocklist → path-level allow carve-outs → path-level blocks → configured default mode → method gate. The default mode SHALL be deny unless explicitly configured otherwise. The method gate SHALL run only on a request the earlier stages allow and SHALL only deny: a request it admits keeps the earlier stages' verdict unchanged, and a request an earlier stage denies is reported by that stage, never by the gate.

#### Scenario: Path carve-out on a blocked host
- **WHEN** a host is blocked but a specific path on it is allow-carved
- **THEN** requests to that path succeed and requests to any other path on that host are denied

#### Scenario: The method gate never widens a verdict
- **WHEN** the same request is evaluated against a policy and against that policy with its `methods` section removed
- **THEN** either both verdicts are identical, or the policy with the section denies with a `method-block:<METHOD>` rule where the other allows; no other difference exists

#### Scenario: A carved-out path is still gated by method
- **WHEN** a host is blocked, a path on it is allow-carved, and the host is method-restricted to `GET`
- **THEN** a GET to the carved path is allowed by the carve-out and a POST to it is denied with `method-block:POST`

#### Scenario: A denial by an earlier stage is reported as such
- **WHEN** the mode is strict-allow, a host is not allow-listed but is method-restricted to `GET`, and the agent sends a POST to it
- **THEN** the request is denied with `default-deny`, exactly as without the restriction

### Requirement: Policy fails closed

A policy file that is missing, unparseable, or internally invalid SHALL cause all egress to be denied.

#### Scenario: Corrupt policy file
- **WHEN** the policy file fails to parse at proxy start or reload
- **THEN** every request is denied and the failure is loudly reported to the operator

#### Scenario: Malformed methods section
- **WHEN** the `methods` section has an unknown key, a rule with a missing, extra or mistyped field, or a method name that is not one to thirty-two upper-case letters, digits and hyphens starting with a letter
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

A `[[methods.restrict]]` rule SHALL have exactly `host` and `allow` (a list of method names, possibly empty). A request to a host matched by any restrict rule SHALL be denied unless its method is listed by every matching rule or a method exception admits it. The denial rule SHALL be `method-block:<METHOD>` (the method as sent) with the host pattern of the first matching rule that omits it. Comparison is exact and no method implies another. Hosts no restrict rule matches are not affected.

#### Scenario: POST to a read-only host
- **WHEN** `api.example.test` is restricted to `GET` and `HEAD` and the agent sends a POST to any path on it
- **THEN** the request is denied with rule `method-block:POST` and pattern `api.example.test`

#### Scenario: GET to a read-only host
- **WHEN** `api.example.test` is restricted to `GET` and `HEAD` and the agent sends a GET to a path the other stages allow
- **THEN** the request is allowed, by the same stage and rule as without the restriction

#### Scenario: Two restrictions on one host intersect
- **WHEN** `*.example.test` is restricted to `GET` and `api.example.test` is restricted to `GET` and `POST`
- **THEN** a POST to `api.example.test` is denied, because one matching restriction does not list it

#### Scenario: A restriction cannot allow what another stage denies
- **WHEN** a host is restricted to `GET` and a path on it is matched by a path block
- **THEN** a GET to that path is denied by the path block, as before

#### Scenario: An empty allow list denies every method
- **WHEN** a host is restricted with `allow = []`
- **THEN** every request to it is denied with `method-block:<METHOD>` unless an exception admits the method on that path

#### Scenario: No method is implied by another
- **WHEN** a host is restricted to `GET` only
- **THEN** a HEAD and an OPTIONS to it are denied with `method-block:HEAD` and `method-block:OPTIONS`

### Requirement: A method exception admits a listed method on a path

A `[[methods.except]]` rule SHALL have exactly `host` (a host pattern), `path` (a path pattern) and `methods` (a list of method names). It SHALL lift the method gate's denial only when its host pattern matches, the method is listed, and every encoded and decoded form of the request path matches its path pattern (charter L22). An admitted request keeps the earlier stages' verdict: an exception never allows on its own. An exception is scoped by its own patterns, not by the restrict rule it lifts.

#### Scenario: Search by POST on a read-only host
- **WHEN** `api.example.test` is restricted to `GET` and an exception admits `POST` on `/rest/api/2/search`
- **THEN** `POST /rest/api/2/search?jql=…` is allowed and `POST /rest/api/2/issue` is denied with `method-block:POST`

#### Scenario: Encoding cannot widen an exception
- **WHEN** the agent sends `POST /rest/api/2/%73earch` or `POST /rest/api/2/search/../issue` against that policy
- **THEN** the exception does not apply and the request is denied with `method-block:POST`

#### Scenario: An exception does not bypass the default mode
- **WHEN** an exception admits `POST` on a path of a host that is neither allow-listed nor carved out in strict-allow mode
- **THEN** the request is denied with `default-deny`

#### Scenario: An exception is as wide as its host pattern
- **WHEN** `*.internal.test` is restricted to `GET`, `vault.internal.test` is restricted with `allow = []`, and an exception admits `POST` on `/webhook` for `*.internal.test`
- **THEN** `POST /webhook` to `vault.internal.test` is admitted; an operator who wants the exception narrower names a narrower host pattern

### Requirement: The request method is an exact HTTP token

The method SHALL be read as the agent sent it, without case folding or trimming, and SHALL be an HTTP token of one to thirty-two ASCII characters from RFC 9110's `tchar` set; any other method SHALL be denied with `fail-closed:bad-method` on every host, before any rule is consulted. A token that appears in no rule evaluates exactly as before. CONNECT SHALL be decided on the host alone, as before; each request inside the tunnel is evaluated with its own method.

#### Scenario: Case is not folded
- **WHEN** the agent sends `post` to a host restricted to `GET`
- **THEN** it is denied with `method-block:post`
- **WHEN** the agent sends `get` to that host
- **THEN** it is denied with `method-block:get`, because `get` is not `GET`

#### Scenario: Malformed method
- **WHEN** a request's method contains a space, a non-ASCII byte or a character outside the token set, or is longer than thirty-two characters
- **THEN** it is denied with `fail-closed:bad-method`, on any host, with or without a `methods` section

#### Scenario: Uncommon tokens are unaffected
- **WHEN** the agent sends `VERSION-CONTROL` to an allow-listed host no restrict rule matches
- **THEN** the request is allowed with `host-allow`, exactly as before this change

#### Scenario: CONNECT is unchanged
- **WHEN** the agent opens a CONNECT tunnel to a host that is allow-listed and method-restricted
- **THEN** the tunnel is opened on the host decision alone and each request inside it is evaluated with its method

### Requirement: A method-restricted host refuses protocol upgrades and method-override headers

For a request to a host matched by a restrict rule, the proxy SHALL deny a request that carries an `Upgrade` header with `method-block:upgrade`, and a request that carries `X-HTTP-Method-Override`, `X-HTTP-Method` or `X-Method-Override` with `method-block:override-header`, whatever the method. Hosts no restrict rule matches are not affected. These guards act on headers, so they live in the proxy rather than the matcher; `tjor policy` cannot preview them, and the README SHALL say so.

#### Scenario: WebSocket handshake to a read-only host
- **WHEN** the agent sends `GET /ws` with `Upgrade: websocket` to a host restricted to `GET`
- **THEN** the request is denied with `method-block:upgrade` and no tunnel is opened

#### Scenario: Override header to a read-only host
- **WHEN** the agent sends a GET with `X-HTTP-Method-Override: DELETE` to a host restricted to `GET`
- **THEN** the request is denied with `method-block:override-header`

#### Scenario: Unrestricted hosts keep their headers
- **WHEN** the agent sends a request with an `Upgrade` or override header to a host no restrict rule matches
- **THEN** the headers are forwarded as before

### Requirement: Denial is enforced before any request byte reaches the upstream

The proxy SHALL compute the verdict, enforce a denial, and perform credential injection and identity handling once the request headers have been read and before any part of the request is sent upstream, so streamed requests are covered like any other. On a denial no byte of the request SHALL reach the upstream: the proxy answers 403 when it can without buffering past the threshold and otherwise closes the request stream; both are recorded in the denial log.

#### Scenario: A large denied body never reaches the upstream
- **WHEN** the agent sends a POST with a declared body above the streaming threshold to a path-blocked or method-denied URL
- **THEN** the upstream receives no byte of the request and the denial is logged with its rule

#### Scenario: A chunked denied body never reaches the upstream
- **WHEN** the agent sends a chunked POST whose body grows past the streaming threshold to a denied URL
- **THEN** the upstream receives no byte of the request and the denial is logged with its rule

#### Scenario: A streamed allowed request is still rewritten
- **WHEN** the agent sends a POST with a body above the streaming threshold to a broker destination, carrying its placeholder credential and a forged `x-agent-*` header
- **THEN** the upstream receives the real credential and no forged identity header

### Requirement: One host identity for the verdict and for injection

A request SHALL be judged on the host its connection was opened to: the CONNECT target for a request inside a tunnel, which SHALL equal the TLS server name, or the URL's host otherwise. A `Host` header (`:authority` for HTTP/2), when present, SHALL name that host, else the request is denied with `fail-closed:host-mismatch`. The evaluated URL SHALL be built from that host, which SHALL also key injection, identity handling and the resolved-address guard.

#### Scenario: Host header lie inside a tunnel
- **WHEN** the agent opens a tunnel to `restricted.test` and sends a request inside it with `Host: allowed.test`
- **THEN** the request is denied with `fail-closed:host-mismatch` and no credential is injected

#### Scenario: Authority lie over HTTP/2
- **WHEN** the agent sends an HTTP/2 request inside a tunnel to `restricted.test` with `:authority` naming another host
- **THEN** the request is denied with `fail-closed:host-mismatch`

#### Scenario: Absolute-form request with a mismatching Host header
- **WHEN** the agent sends `GET http://a.test/ HTTP/1.1` to the proxy with `Host: b.test`
- **THEN** the request is denied with `fail-closed:host-mismatch`

#### Scenario: A request without a Host header is judged on its URL
- **WHEN** the agent sends an HTTP/1.0 absolute-form request with no `Host` header
- **THEN** the request is judged on the URL's host

### Requirement: The method gate's limits are stated

The README, this specification and the overview slide SHALL state what the gate does not do: it decides on the method token and the headers named above, not on what a request does; a POST exception admits every POST to its path; `*` spans `/` in a path pattern; `git fetch` and `git clone` POST to `git-upload-pack`; CONNECT is decided on the host and each inner request on its own method.

#### Scenario: Operator reads the limits
- **WHEN** an operator reads the README's egress policy section, this specification or the policy slide
- **THEN** each names those limits
