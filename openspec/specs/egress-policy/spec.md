# egress-policy Specification

## Purpose
The semantics of the egress allowlist: how allow/block rules are evaluated, and the guarantees that evaluation is identical everywhere and cannot be bypassed by encoding tricks or broken configuration.

## Requirements

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

### Requirement: Denial is enforced before any request byte is forwarded

The proxy SHALL compute the verdict, enforce a denial, inject credentials and handle identity at the headers stage, before any byte of the request is sent upstream. It SHALL negotiate HTTP/1.1 only, so every body is declared there. A denied request with no body or a bounded `Content-Length` gets the 403 (nothing forwarded, no `100 Continue`), except one asking for a `100 Continue` before a body, which is closed at once; any other denied request is closed before a body byte is read.

#### Scenario: A large denied body is never forwarded
- **WHEN** the agent sends a POST with a declared body above the streaming threshold to a denied URL
- **THEN** the connection is closed without a response, no byte of the request is forwarded, and the denial is logged with its rule

#### Scenario: A chunked denied body is never forwarded
- **WHEN** the agent sends a chunked POST to a denied URL
- **THEN** the connection is closed at the headers stage, no byte of the request is forwarded, and the denial is logged with its rule

#### Scenario: A bounded denied request gets the 403 and the connection survives
- **WHEN** the agent sends a denied request with no body or with a `Content-Length` at or below the threshold, and does not ask for a `100 Continue` before a body
- **THEN** it receives the 403 with the rule, nothing is forwarded, and a following request on the same connection is judged on its own

#### Scenario: A denied request with Expect gets no 100 Continue
- **WHEN** the agent sends a denied request with `Expect: 100-continue` and a body to send
- **THEN** no `100` is sent and the connection is closed at once, since a 403 could only follow a body the client is waiting to be invited to send
- **WHEN** the agent sends a denied request with `Expect: 100-continue` and no body
- **THEN** it reads the 403, never a `100`

#### Scenario: An interrupted denied upload is still logged
- **WHEN** the agent sends the headers of a denied upload, part of its body, and closes the connection
- **THEN** no byte of the request is forwarded and the denial is logged with its rule, whether or not the agent read the 403

#### Scenario: A streamed allowed request is still rewritten
- **WHEN** the agent sends a POST with a body above the streaming threshold to a broker destination, carrying its placeholder credential and a forged `x-agent-*` header
- **THEN** the upstream receives the real credential and no forged identity header

#### Scenario: HTTP/2 is not negotiated
- **WHEN** a client offers `h2` and `http/1.1` in its TLS handshake through the proxy
- **THEN** `http/1.1` is selected and the request inside the tunnel is served
- **WHEN** a client offers only `h2`
- **THEN** the handshake completes without a negotiated protocol and an HTTP/2 preface is refused; nothing is forwarded

#### Scenario: The proof would notice a partial request
- **WHEN** the conformance suite proves the denial scenarios above
- **THEN** it does so against an upstream fixture that records every accepted connection and every request it starts reading, after a positive control of the same shape has arrived complete, with a sentinel request bounding the observation, and with the denial log checked by count for the rule of each closed connection

#### Scenario: The conformance trust anchor does not disable verification
- **WHEN** the conformance proxy trusts the fixture's certificate for the fixture's names
- **THEN** a TLS tunnel to an allowed name the certificate does not cover is refused by upstream verification, and `tjor run` never writes that trust configuration

### Requirement: One host identity for the verdict and for injection

A request SHALL be judged on the host its connection was opened to: the CONNECT target for a request inside a tunnel, which SHALL equal the TLS server name, or the URL's host otherwise. A `Host` header, when present, SHALL name that host, else the request is denied with `fail-closed:host-mismatch`. The evaluated URL SHALL be built from that host, which SHALL also key injection, identity handling and the resolved-address guard.

#### Scenario: Host header lie inside a tunnel
- **WHEN** the agent opens a tunnel to `restricted.test` and sends a request inside it with `Host: allowed.test`
- **THEN** the request is denied with `fail-closed:host-mismatch` and no credential is injected

#### Scenario: A TLS tunnel is judged on its server name
- **WHEN** the agent opens a TLS tunnel to an allowed host and sends a request inside it with a matching `Host`
- **THEN** the request is judged and served on that host, and the same request with another host in `Host` is denied with `fail-closed:host-mismatch`

#### Scenario: Absolute-form request with a mismatching Host header
- **WHEN** the agent sends `GET http://a.test/ HTTP/1.1` to the proxy with `Host: b.test`
- **THEN** the request is denied with `fail-closed:host-mismatch`

#### Scenario: Absolute-form target inside a tunnel
- **WHEN** the agent sends `GET http://b.test/x HTTP/1.1` inside a tunnel to `a.test` with `Host: a.test`
- **THEN** the request is denied with `fail-closed:host-mismatch`, because the retained request-target authority would be re-emitted upstream

#### Scenario: A request without a Host header is judged on its URL
- **WHEN** the agent sends an HTTP/1.0 absolute-form request with no `Host` header
- **THEN** the request is judged on the URL's host

#### Scenario: A tunnel whose server name differs from its target
- **WHEN** a tunnel was opened to one host and the TLS server name inside it is another
- **THEN** every request inside it is denied with `fail-closed:host-mismatch`

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

#### Scenario: A redirect is a new request
- **WHEN** an excepted POST on a read-only host is answered with a 307 to a path with no exception and the client follows it with a POST
- **THEN** the second request is denied with `method-block:POST` like any other POST to that path

### Requirement: The request method is an exact HTTP token

The method SHALL be read as the agent sent it, without case folding or trimming, and SHALL be an HTTP token (RFC 9110 `tchar`) of one to thirty-two ASCII characters; any other method SHALL be denied with `fail-closed:bad-method` on every host, before any rule is consulted. The bound is a stated limit. On a host no restrict rule matches, a token within the bound evaluates as before. CONNECT is decided on the host alone; each request inside the tunnel is evaluated with its own method.

#### Scenario: Case is not folded
- **WHEN** the agent sends `post` to a host restricted to `GET`
- **THEN** it is denied with `method-block:post`
- **WHEN** the agent sends `get` to that host
- **THEN** it is denied with `method-block:get`, because `get` is not `GET`

#### Scenario: Malformed method
- **WHEN** a request's method contains a space, a non-ASCII byte or a character outside the token set
- **THEN** it is denied with `fail-closed:bad-method`, on any host, with or without a `methods` section

#### Scenario: The length bound
- **WHEN** the agent sends a thirty-two-character token to an allow-listed host no restrict rule matches
- **THEN** the request is allowed with `host-allow`
- **WHEN** the agent sends a thirty-three-character token to any host
- **THEN** it is denied with `fail-closed:bad-method`

#### Scenario: Uncommon tokens are unaffected
- **WHEN** the agent sends `VERSION-CONTROL` to an allow-listed host no restrict rule matches
- **THEN** the request is allowed with `host-allow`, exactly as before this change

#### Scenario: CONNECT is unchanged
- **WHEN** the agent opens a CONNECT tunnel to a host that is allow-listed and method-restricted
- **THEN** the tunnel is opened on the host decision alone and each request inside it is evaluated with its method

### Requirement: A method-restricted host refuses protocol switches and method-override headers

On a host matched by a restrict rule, the proxy SHALL deny a request that asks for a protocol switch (`Upgrade`, `Connection: upgrade` or `Sec-WebSocket-Version`) with `header-block:upgrade`, and one carrying `X-HTTP-Method-Override`, `X-HTTP-Method` or `X-Method-Override` with `header-block:method-override`, and SHALL refuse a `101` from such a host (`header-block:upgrade-response`). No rule lifts a guard: a host needing such headers is left unrestricted; the README SHALL say so.

#### Scenario: WebSocket handshake to a read-only host
- **WHEN** the agent sends `GET /ws` with `Upgrade: websocket` to a host restricted to `GET`
- **THEN** the request is denied with `header-block:upgrade` and no channel is opened

#### Scenario: A switch asked for without an Upgrade header
- **WHEN** the agent sends a GET with only `Sec-WebSocket-Version: 13`, or with `Connection: upgrade`, to a host restricted to `GET`
- **THEN** the request is denied with `header-block:upgrade`

#### Scenario: Override header to a read-only host
- **WHEN** the agent sends a GET with `X-HTTP-Method-Override: DELETE` to a host restricted to `GET`
- **THEN** the request is denied with `header-block:method-override`

#### Scenario: A 101 from the upstream of a read-only host
- **WHEN** a request to a host restricted to `GET` carried no switch marker and the upstream answers `101`
- **THEN** the response never reaches the agent, the connection is closed, and the denial is logged as `header-block:upgrade-response`

#### Scenario: Unrestricted hosts keep their headers
- **WHEN** the agent sends a request with an `Upgrade` or override header to a host no restrict rule matches
- **THEN** the headers are forwarded as before, and a `101` from that host is handled as the proxy does today

#### Scenario: A method named like a guard is still a method
- **WHEN** the agent sends a request whose method is literally `upgrade` to a host restricted to `GET`
- **THEN** it is denied with `method-block:upgrade`, which the denial log and its hints treat as a non-standard method token

### Requirement: The method gate's limits are stated

The README, this specification and the overview slide SHALL state what the gate does not do, as listed in the scenario below.

#### Scenario: Operator reads the limits
- **WHEN** an operator reads the README's egress policy section, this specification or the policy slide
- **THEN** each names these limits: the gate decides on the method token (at most thirty-two characters) and the named headers, not on what a request does, so a POST exception on a GraphQL endpoint admits mutations; listing `GET` admits neither `HEAD` nor `OPTIONS`; a POST exception admits every POST to its path and `*` spans `/`; `git fetch` and `git clone` POST to `git-upload-pack`; a header guard has no exception; CONNECT is decided on the host and each inner request on its own method
