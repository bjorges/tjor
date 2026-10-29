# Spec Delta

## ADDED Requirements

### Requirement: Denial is enforced before any request byte is forwarded

The proxy SHALL compute the verdict, enforce a denial, and perform credential injection and identity handling once the request headers are read and before any part of the request is sent upstream. It SHALL negotiate HTTP/1.1 only, so every request declares its body at that point. A denied request with no body or a `Content-Length` at or below the streaming threshold SHALL get the 403 (body consumed, nothing forwarded, no `100 Continue`); otherwise its connection SHALL be closed without a response before any body byte is consumed.

#### Scenario: A large denied body is never forwarded
- **WHEN** the agent sends a POST with a declared body above the streaming threshold to a denied URL
- **THEN** the connection is closed without a response, no byte of the request is forwarded, and the denial is logged with its rule

#### Scenario: A chunked denied body is never forwarded
- **WHEN** the agent sends a chunked POST to a denied URL
- **THEN** the connection is closed at the headers stage, no byte of the request is forwarded, and the denial is logged with its rule

#### Scenario: A bounded denied request gets the 403 and the connection survives
- **WHEN** the agent sends a denied request with no body or with a `Content-Length` at or below the threshold
- **THEN** it receives the 403 with the rule, nothing is forwarded, and a following request on the same connection is judged on its own

#### Scenario: A denied request with Expect gets no 100 Continue
- **WHEN** the agent sends a denied request with `Expect: 100-continue`
- **THEN** the first response it reads is the 403, never a `100`

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

#### Scenario: A request without a Host header is judged on its URL
- **WHEN** the agent sends an HTTP/1.0 absolute-form request with no `Host` header
- **THEN** the request is judged on the URL's host

#### Scenario: A tunnel whose server name differs from its target
- **WHEN** a tunnel was opened to one host and the TLS server name inside it is another
- **THEN** every request inside it is denied with `fail-closed:host-mismatch`
