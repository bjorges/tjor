# ADR 0012 — Headers-stage enforcement, HTTP/1.1 only, one host identity

**Date:** 2026-10-29 · **Status:** accepted

Two defects in how the egress proxy enforced its verdicts were found while
grounding the method-gate plan (#66) in `proxy/addon.py` and the pinned
mitmproxy 12.1.2 source. Both existed on `main`; both reviewers of that plan
asked for them to land first, on their own, because every later policy
feature inherits them. This ADR records the three decisions that fix them and
the facts they rest on, so a later refactor cannot undo them by accident.

## Context: what mitmproxy does, in order

- `request` (the hook the addon used) fires once the whole body has been
  read. With `stream_large_bodies=1m` a request whose declared body exceeds
  the threshold, or whose chunked body grows past it, is **streamed**: in
  `state_wait_for_request_headers`, `check_body_size` runs *before* the
  `requestheaders` hook and sets `flow.request.stream`; right after that hook
  `start_request_stream` opens the upstream connection and sends the request
  headers, then streams the body, and only then fires `request`. So for a
  streamed request the addon's verdict, its 403, credential injection and
  identity stripping all came *after* the headers (and the agent's placeholder
  credential, and any forged `x-agent-*` header) had gone upstream.
- `requestheaders` is the last hook at which nothing has gone upstream. A
  response set there on a non-streaming flow makes mitmproxy consume the
  declared body and answer without an upstream request. `flow.kill()` there
  (`check_killed` runs right after the hook) closes the HTTP/1 connection
  without a response, before `start_request_stream` and before any body byte
  is consumed. `start_request_stream` raises `NotImplementedError` on a
  streaming flow that already has a response; `server.py` logs that as
  "mitmproxy has crashed!" per event and carries on.
- The declared body comes from `expected_http_body_size`: `None` for a
  chunked request, the `Content-Length`, else `0`. Over HTTP/1.1 that is
  exact (`validate_inbound_headers`, on by default, rejects any other
  framing). Over HTTP/2 a request with no `Content-Length` reports `0` while
  DATA frames may still follow; the hook cannot tell an empty body from an
  unbounded one. The `h2` library resets a stream whose DATA exceeds a
  declared length.
- The verdict was computed on `flow.request.pretty_url`, whose host is the
  client's `Host` header — which mitmproxy's own docstring calls spoofable —
  while injection keyed on the TLS server name (ADR 0007). Inside a tunnel to
  A, an inner request with `Host: B` was judged under B's rules and sent to A
  carrying A's credential. Inside a tunnel the inner layer runs in transparent
  mode, so `flow.request.host` is the tunnel's server address (the #41 pinned
  IP); `flow.client_conn` is the same object, with a stable `id`, for the
  CONNECT flow and every flow inside its tunnel.
- ALPN with `http2=false`: `alpn_select_callback` mirrors the upstream's
  protocol when the client offered it, else picks the client's first HTTP/1
  offer; a client offering only `h2` gets `NO_OVERLAPPING_PROTOCOLS`, which is
  OpenSSL's "no acknowledgement": the handshake completes with no protocol and
  the HTTP/2 preface the client then sends is killed by mitmproxy's default
  `DisableH2C` addon. An upstream that negotiates no ALPN is mirrored as none.
- `ssl_verify_upstream_trusted_ca`, when set, is loaded *instead of* the
  bundled `certifi` store; hostname verification against the SNI is unchanged.
  mitmproxy loads `config.yaml` from its confdir at start.
- A kill issued while the same client is still sending does **not** close the
  client socket promptly in mitmproxy 12.1.2: the connection handler's task is
  cancelled from inside its own event processing, it never reaches its
  `writer.close()`, and the socket lingers (receive queue full, descriptor
  held) until garbage collection — so a client mid-upload blocks until its own
  timeout instead of failing at once. Verified against the real proxy with an
  instrumented copy; mitmproxy's own `body_size_limit` refusal shows the
  identical symptom. Plain asyncio closes such a socket immediately. The live
  handler is reachable through the proxyserver addon's connection registry,
  the table mitmproxy's `inject` commands use, and aborting its client
  transport closes the socket now.

## Decisions

1. **Verdict, denial, injection and identity handling happen in
   `requestheaders`.** One body rule decides the denial's shape: no body, or a
   `Content-Length` at or below the streaming threshold, on a flow not already
   streaming → the 403 (mitmproxy consumes the declared body and answers;
   `Expect` is removed first so no `100 Continue` invites the body before the
   answer; the connection survives for the next request). One exception: a
   denied request that sends `Expect: 100-continue` *with* a body is closed
   at once, because mitmproxy can only answer after the body and a client
   honouring `Expect` sends the body only after a `100` — a 403 could never
   arrive promptly, and a client that never sends its body must not hang.
   Otherwise — chunked, or declared past the threshold — the flow is killed and, because mitmproxy
   alone would leave the socket open (Context), the addon aborts the client
   transport itself through the proxyserver addon's connection registry:
   connection closed now, no response, no body byte consumed; the kernel
   resets the connection and the client's pending send fails. That reach into
   a pinned mitmproxy's registry is best effort — if it ever fails, the kill
   alone stands and the client learns of the denial when its send times out
   or it reads — and the conformance probes would show the regression as a
   timeout. The `request` hook keeps only the observe-only body scan (#62)
   and a fail-closed check that a verdict was recorded. The threshold is read from mitmproxy's own option, not assumed.
   What is guaranteed is *no byte of the request is forwarded*; a tunnel's
   upstream connection, opened at CONNECT time, exists and stays idle, and one
   network read can hold headers and body, so "unread" is not claimed. An
   upload the client interrupts never sees its 403, but the denial was logged
   at the headers stage.

2. **HTTP/1.1 only** (`--set http2=false`, next to `rawtcp=false`;
   `validate_inbound_headers=true` made explicit as the framing precondition).
   This is a **compatibility decision**: the rule in (1) is exact only when the
   framing declares the body at the headers stage, which HTTP/1.1 guarantees
   and HTTP/2 does not. Costs, stated: no gRPC or other HTTP/2-only protocols
   inside the cage, and no HTTP/2 multiplexing. Every ordinary client (curl,
   gh, git, Go, Node, Python) offers `http/1.1` and falls back; an h2-only
   client completes its handshake without a protocol and its preface is
   refused, so nothing is forwarded. Alternatives weighed:
   - *Keep HTTP/2, kill every denied HTTP/2 request without a declared
     length.* Sound, but every bodiless denial over HTTP/2 (a GET or DELETE)
     loses its 403 page and the reset carries no reason. Rejected.
   - *Keep HTTP/2, kill only undeclared-length requests whose method
     conventionally carries a body (POST, PUT, PATCH), answer 403 to the rest.*
     Keeps the page, HTTP/2 and gRPC. Two costs: a hostile client sending DATA
     on a GET past the threshold drives mitmproxy's late switch to streaming
     into its "response already set" exception (one error log per megabyte,
     body dropped, nothing forwarded, the 403 still sent at end of message);
     and it cannot be proven in conformance — the fixture stack has no HTTP/2
     upstream, and mitmproxy mirrors the upstream's protocol to the client.
     **This is the fallback if HTTP/2 inside the cage turns out to matter**;
     unit tests over fake flows would be its proof. The "bodiless requests
     never send DATA" argument is true and was *not* used to pick (2): a
     hostile client can send DATA on any method.
   - *Keep HTTP/2, answer 403, rely on that exception as the backstop.*
     Fail-closed in effect, undesigned. Rejected.

3. **One host identity.** Every request is judged on the host its connection
   was opened to: the CONNECT target, recorded per client connection id when
   the CONNECT is allowed and forgotten when the client disconnects, which
   must equal the TLS server name when there is one (mitmproxy verifies the
   upstream certificate against it, so this is the identity injection already
   trusts); without a recorded tunnel, the server name; for a plain
   absolute-form request, the URL host from the request line. A `Host` header,
   when present, must name that host, and so must a request-target authority
   a request inside a tunnel retains (mitmproxy clears it in regular mode only
   and re-emits it upstream as absolute-form), else
   `fail-closed:host-mismatch`. Hosts are compared after the port is split
   off and a non-ASCII name is converted to its A-label, so `example.test.:8443`
   and a U-label `Host` compare as the SNI does. The URL the matcher evaluates
   is rebuilt on the judged host; `pretty_url` is no longer consulted for any
   security decision. The same host keys injection,
   identity handling, the resolved-address guard, the #62 scan and the #50
   counter. No known client sends a `Host` that disagrees with its connection
   host; the denial names itself so it is diagnosable.

## Proof

Conformance (`images/conformance/`) now has an upstream that would notice: the
echo fixture records every accepted connection and every request it starts
reading (method, path, bytes received, complete or not; connections are
recorded in the accept loop, before any handler thread runs), serves TLS from
a conformance-only certificate, and advertises ALPN `http/1.1`. Twelve probes
cover large, chunked, bounded (403 and a surviving connection), `Expect` and
interrupted denials with positive controls of the same shape and a sentinel
request bounding the observation (snapshots are read until two agree); the
streamed broker rewrite; `Host` lies over plain and TLS tunnels and in
absolute form, and an absolute-form target inside a tunnel; the ALPN outcome;
and a negative control, after a positive one, showing the conformance trust
anchor does not disable upstream verification (the proxy's own 502 naming
the verification failure). Every probe that provokes a denial declares it,
older probes included, and `tjor conformance` requires the session's denial
log to be exactly that multiset: per-pair counts and line totals match, and a
run that declared nothing fails.

## Consequences

- A denied large or chunked upload ends in a closed connection, not a 403;
  `tjor denials` has the rule (README, "What a denial looks like").
- HTTP/2-only protocols are unavailable inside the cage (README residual).
- The conformance topology adds a trust anchor to the proxy for its temporary
  session only: `cmd_conformance` is the one writer of `proxy-ca/config.yaml`,
  the certificate covers the test aliases alone, and a probe shows a name it
  does not cover is refused.
- The method gate (#66) builds on this hook, this host identity and this
  fixture.
- When the mitmproxy pin is bumped: the client abort reaches into the
  proxyserver addon's `connections` registry and the transport behind it, and
  the body rule reads `stream_large_bodies`; the conformance suite (the
  enforcement probes in particular) is the check that both still hold, so a
  bump is not done without a green conformance run.
