# Proposal

## Why

Two defects in how the egress proxy enforces its verdicts exist on `main` today. They were found while grounding the plan for the method gate (#66, PR #86) in `proxy/addon.py` and the pinned mitmproxy 12.1.2 source, and both reviewers of that plan asked for them to land first, on their own, because every later policy feature inherits them.

- **Enforcement runs after the body.** The addon decides in mitmproxy's `request` hook, which fires once the whole body has been read. With `stream_large_bodies=1m` (compose.yaml) a request whose declared body exceeds 1 MiB, or whose chunked body grows past it, is streamed: mitmproxy opens the upstream connection and sends the request headers *before* `request` fires. For such a request a path block answers 403 only after the request has been delivered, and the broker, gateway and identity handling in the same hook come too late: the upstream receives the agent's placeholder `Authorization` and any forged `x-agent-*` header. A `git push` of a pack over 1 MiB toward a brokered host, or a large inference request toward the gateway, hits this today.
- **Policy and injection use different host identities.** The verdict is computed on `flow.request.pretty_url`, whose host is the client's `Host` header; injection keys on the TLS SNI (ADR 0007). Inside a tunnel to host A, an inner request with `Host: B` is judged under B's rules and sent to A carrying A's credential.

Enforcing at the headers stage is only exact when the proxy knows, at that point, whether and how much body follows. HTTP/1.1 always says (no body, a `Content-Length`, or chunked); HTTP/2 does not (DATA frames may follow headers that declare nothing). The proxy therefore stops negotiating HTTP/2, a compatibility decision with a stated cost.

## What Changes

- **Enforcement moves to the headers stage.** The verdict, the denial, credential injection and identity handling run in mitmproxy's `requestheaders` hook. A denied request with no body or a `Content-Length` at or below the streaming threshold receives the 403 (its body is consumed, nothing is forwarded, no `100 Continue` is sent); a denied request with a larger declared body or a chunked body has its connection closed without a response, before any body byte is consumed. In both cases no byte of the request is forwarded and the denial is logged with its rule. A streamed allowed request now carries the real credential and stripped identity headers. The `request` hook keeps the #62 body scan and a fail-closed check that a verdict was recorded.
- **HTTP/1.1 only.** The proxy command gains `--set http2=false` next to `rawtcp=false`, and makes the already-default `validate_inbound_headers=true` explicit, since the body rule depends on it. Clients offering both ALPN values fall back to HTTP/1.1 transparently; a client offering only `h2` completes its handshake without a negotiated protocol, and its HTTP/2 preface is then refused by mitmproxy's existing h2c guard, so nothing is forwarded. Cost: no gRPC or other HTTP/2-only protocols inside the cage, and no HTTP/2 multiplexing.
- **One host identity.** A request is judged on the host its connection was opened to: the CONNECT target for a tunnelled request (which must equal the SNI), the URL host otherwise. The `Host` header must name the same host; a mismatch is denied with `fail-closed:host-mismatch`. The same host keys injection, identity handling and the resolved-address guard.
- **Proof that would notice.** The echo fixture records every accepted connection and every request it starts reading, serves TLS from a conformance-only certificate the proxy trusts through its confdir, and advertises `http/1.1`; eleven probes with positive controls prove zero forwarded bytes on large, chunked and interrupted denied requests, the 403 and a surviving connection on bounded ones, the `Expect` case, the streamed broker rewrite, the host identity over plain and TLS tunnels, the HTTP/1.1-only negotiation, and that the trust anchor does not disable upstream verification; the denial log is checked host-side, by count, for every rule the probes provoke.
- **Docs and record.** README residuals (a closed connection on a large or chunked request means a denial; HTTP/1.1 only), ADR 0012 for the enforcement point, the protocol decision with its rejected alternatives, and the host identity; CHANGELOG Fixed and Changed entries; the `egress-policy` spec amended and its slides re-read.

Compatibility. Three operator-visible changes, all in the fail-closed direction: HTTP/2 is no longer negotiated; a request whose `Host` disagrees with the host its connection was opened to is denied (no known client does this); a denied request with a large or chunked body sees a closed connection instead of a 403. No policy file changes.

## Capabilities

### New Capabilities
<!-- none: the enforcement point and the host identity are properties of the existing egress policy -->

### Modified Capabilities
- `egress-policy`: two added requirements — denial is enforced before any request byte is forwarded (HTTP/1.1 only, with the bounded/unbounded rule, `Expect`, follow-up requests, and the proof's observation boundary), and one host identity for the verdict and for injection.

## Impact

- `proxy/addon.py`: a `requestheaders` hook carrying verdict, denial, injection and identity handling; the tunnel-host registry (`http_connect`, `client_disconnected`); the host-identity check; `_logical_host` redefined on it; the `request` hook reduced to the body scan and a fail-closed check. `compose.yaml`: `--set http2=false` and `--set validate_inbound_headers=true` on the proxy command. `python/tests/test_addon_guards.py`: hook tests over fake flows.
- `images/conformance/echo.py` (every method reflected, a connection and request recorder at `/_seen`, a TLS listener with ALPN `http/1.1`), `compose.yaml` (TLS mount on the echo fixture; the proxy CA mounted into the conformance container), `bin/tjor cmd_conformance` (certificate, confdir `config.yaml`, denial-log check), `images/conformance/probes.py` (eleven probes), `python/gen_boundary_matrix.py`, `docs/boundary-matrix.md` regenerated.
- Docs: README "Egress policy" residuals, `docs/decisions/0012-headers-stage-enforcement-and-host-identity.md`, `CHANGELOG.md` under `[Unreleased]`, the three slides tagged `egress-policy` re-read and re-pinned.
- Not affected: `python/tjor_policy.py` (the matcher and its verdicts are unchanged), the DNS sidecar, the broker and identity modules' own logic (they are called from a different hook with the same host).
- Follow-up: the method gate (`egress-method-gate`, PR #86) builds on the hook, the judged host and the fixture introduced here.
