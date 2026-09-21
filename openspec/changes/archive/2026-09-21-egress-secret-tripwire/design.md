# Design

## Context

See proposal.md — Why; ADR 0010; and #62's design-first acceptance. Grounding in the repo:

- The proxy MITMs TLS, so `proxy/addon.py`'s `request` hook (line ~806) has the decoded outbound body of allowed requests. `GATEWAY_HOST` (canonicalized) is the D4 gateway's single inference host; when the gateway is enabled, all inference is concentrated there.
- `python/tjor_secrets.py` has `redact()` and `contains_secret()` (both total by construction after the v0.18.9 hardening). There is no "which kinds matched" accessor yet.
- mitmproxy buffers request bodies up to `stream_large_bodies` (1m); beyond that the body is streamed and `flow.request.content` is not fully materialized.
- The `request` hook is wrapped in a **fail-closed** guard (v0.18.9): any exception escaping the allowed branch DENIES the request. So a scan added there must never let an exception reach that guard — a scan bug must not turn a legitimate inference call into a 403.
- The #50 log-volume counter is the established pattern for a per-session, bind-mounted, bounded signal file that the `tjor down` recap aggregates (mirrors the denial log). `_record_log_volume` is the fail-safe-sink template.

## Goals / Non-Goals

**Goals:**
- Catch *accidental* verbatim leakage of a known-shape secret into an outbound inference body, and surface it to the operator at teardown.
- Never alter, block, or delay the request; never re-log the secret value.
- Bounded latency; scoped to inference hosts only.

**Non-Goals (stated, not glossed):**
- **Not a guarantee.** The agent can trivially evade (base64/split/encode) — this is a best-effort tripwire against accident, not DLP against a hostile agent. The ADR says so plainly.
- No redaction, blocking, or rate-limiting of the request (deferred; each is a separate correctness/latency decision).
- No scanning of response bodies, non-inference egress, or bodies beyond the byte cap / streamed past `stream_large_bodies`.

## Decisions

1. **Observe-only: signal, never alter or block (the chosen match→action).** On a match the proxy records a per-session signal and forwards the request byte-for-byte unchanged. This is the whole safety story: a false positive produces only a benign operator note — it can never corrupt a prompt or break inference, which is exactly the risk that made redact/block too costly for an evadable boundary.
2. **Scope = configured inference hosts.** Scan the body only when `flow.request.host` is in `SCAN_HOSTS` (from `TJOR_SECRET_SCAN_HOSTS`): the gateway host auto-included when the D4 gateway is enabled, plus any host listed in `[secrets] scan_hosts` for gateway-less setups. The gateway is the clean chokepoint (D4 concentrates inference on one host); gateway-less users must name their inference host to opt in — a documented limitation, not silent partial coverage.
3. **Bounded scan (latency stance).** Scan at most `scan_max_bytes` (`[secrets] scan_max_bytes`, default 262144 = 256 KiB) of the body; if the body is streamed past `stream_large_bodies` (`content` unavailable) the request is forwarded unscanned. A pasted secret shows up early in a prompt, so a bounded prefix catches the accidental case while keeping per-request cost predictable on the inference hot path. Beyond the cap is honestly out of scope.
4. **Fail-safe AND isolated from the fail-closed hook (the v0.18.9 lesson).** The scan runs in its own `try/except Exception: pass` inside the allowed branch, before `return`, so a scan error is swallowed *there* and can never reach the hook's outer fail-closed guard — a scan bug must not deny a legitimate inference request. Observe-only means "fail" = forward unscanned.
5. **The signal records count + kinds, never the value or the body.** On a match, append `host\t<kinds>` (kinds from `kinds_present`, e.g. `github-token,aws-access-key-id`) to a bounded, bind-mounted `TJOR_SECRET_SCAN_LOG` file — never the matched substring, never the body (re-logging the secret is the exact #6 concern). `tjor down` aggregates into one honest line, e.g. `this session sent N inference request(s) containing what looked like a discovered secret (kinds: …) — best-effort tripwire; content reaches allowed egress by design`.
6. **`kinds_present(text) -> list[str]`** added to `tjor_secrets.py`: total (per-pattern guard, like `redact`), returns the sorted unique matched kinds with no values — so the signal names *what* shape without handling the secret.
7. **ADR 0011 is the durable record; `skip_specs`.** Mirrors #6: the design decision + a working proof, recorded in an ADR. A spec *requirement* would overclaim a deliberately best-effort, evadable tripwire; the ADR states the contract and its limits honestly instead.

## Risks / Trade-offs

- [Trivially evadable] → stated in the ADR and the recap line itself ("best-effort tripwire; content reaches allowed egress by design"). Its value is catching *accidents*, and producing signal that would justify (or not) a future enforcement step.
- [Bounded scan misses secrets past the cap / in streamed bodies] → documented; the cap is tunable. A pasted secret is near the top of a prompt in practice.
- [Gateway-less setups aren't covered unless configured] → documented; `[secrets] scan_hosts` is the opt-in.
- [Reading `flow.request.content` buffers the body] → mitmproxy already buffers up to `stream_large_bodies`; observe-only reads, never rewrites, so no streaming/correctness change.

## Migration Plan

Additive: a detector helper, a scan in the request hook (self-guarded), two config knobs + exports, one bind-mounted signal file, a recap line, an ADR, tests. No policy/spec/product-contract change. Rollback is a plain revert. Patch release; the proxy image rebuilds per release.

## Open Questions

- Enforcement (redact-and-forward or block) stays deferred until the tripwire produces real signal and the prompt-corruption / latency cost of acting is understood — a separate decision, explicitly out of scope here.
