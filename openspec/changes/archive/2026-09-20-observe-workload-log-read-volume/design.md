# Design

## Context

See proposal.md — Why, and #50's archived analysis (`openspec/changes/archive/2026-09-14-add-exfiltration-conscious-profile-guide/design.md`, Decision 3), which recorded "observability before enforcement" as the path forward. Grounding in the repo:

- The proxy MITMs the cluster API origin (kube broker, #45/#57), so `pods/log` responses transit `proxy/addon.py`. `KUBE_API_HOSTS` names the configured cluster API hosts; it is non-empty only when the kube broker is active.
- mitmproxy streams large bodies (`stream_large_bodies=1m`) and any `follow=true` log tail, so `flow.response.content` is NOT fully materialized for exactly the large reads we most want to count. Byte counting must be stream-aware.
- The denial log (#23) is the established pattern for "proxy writes a bounded, attacker-influenced, session-owned file that a host command reads": a bind-mounted file (`compose.yaml`: `${TJOR_SESSION_DIR}/denials.log:/denials.log`, `TJOR_DENIAL_LOG=/denials.log`), pre-created in `bin/tjor`, appended fail-safe by `_log_denial`, aggregated at teardown by `cmd_down` and rendered through `tjor_safeprint`.
- `cmd_down` already prints the #42 denial recap to stderr, quiet when empty.

## Goals / Non-Goals

**Goals:**
- Count how much workload-log content a session reads, per pod, including streamed/`follow` reads.
- Surface it once, at teardown, alongside the existing denial recap.
- Zero effect on the read itself, and zero overhead for non-kube traffic.

**Non-Goals (this change; deferred per #50):**
- Any enforcement: threshold, deny, rate limit, truncation, content inspection/redaction.
- New config surface. Counting is automatic and observation-only.
- Counting non-log egress volume (only `pods/log` is in scope).

## Decisions

1. **Count via a stream passthrough installed in `responseheaders`, not by buffering.**
   A new `responseheaders` hook checks: kube broker active (`KUBE_API_HOSTS` non-empty), `flow.request.host in KUBE_API_HOSTS`, and the request path matches `^/api/v1/namespaces/[^/]+/pods/[^/]+/log` (pod name captured). On a match it sets `flow.response.stream` to a counting passthrough — a callable that tallies `len(chunk)` and returns the chunk **unmodified**, flushing the per-pod total on the end-of-stream sentinel (`b""`). This counts small, large, and `follow` reads through one path, never buffers the body, and never alters it. Chosen over (a) reading `flow.response.content` in the `response` hook — wrong for streamed/`follow` bodies, which are the big ones — and (b) trusting `Content-Length` — absent for chunked/`follow` responses.

2. **Persist to a session-owned counter file, mirroring the denial log.**
   The addon appends `pod\tbytes\n` (one line per completed log read) to a bind-mounted file, `TJOR_LOG_VOLUME_LOG=/logvolume.log` → `${TJOR_SESSION_DIR}/logvolume.log`, pre-created in `bin/tjor` like `denials.log`, and bounded by a line cap (reuse the denial-log cap style) so a pathological session can't grow it unbounded. Per-pod lines let the recap report both total bytes and distinct-pod count; aggregation is the reader's job, matching the denial recap.

3. **Fail-safe, like `_log_denial`.**
   Both the stream passthrough and the file append are wrapped so any error is swallowed — a counting failure MUST NOT raise into the proxy, alter the body, or fail-open. The passthrough returns the original chunk even if tallying throws (an exception in a stream callback would otherwise corrupt the response).

4. **Surface in the `tjor down` recap.**
   After the #42 denial recap, `cmd_down` reads `logvolume.log` (when non-empty), sums bytes, counts distinct pods, and prints one stderr line — e.g. `tjor: this session read 42.7 MB of workload logs across 6 pod(s) — review what left the session with 'tjor denials'` — with pod identifiers (though only the count is shown) sanitized via `tjor_safeprint`. Quiet when the file is empty/absent. Human-readable size formatting (KB/MB/GB).

5. **Scope strictly to kube `pods/log`.** No stream is installed for any other request, so non-kube sessions and non-log kube calls pay nothing and are never counted.

## Risks / Trade-offs

- [Forcing streaming on small log reads] → The passthrough makes even small `pods/log` responses stream. Acceptable: these are already MITM'd, the passthrough is a thin tally, and it unifies the code path. No correctness impact.
- [Per-read line growth for many small reads] → Bounded by the same line-cap discipline as the denial log; a cap notice is appended when hit.
- [Pod names are attacker-influenced] → Only a count is displayed, and any rendered identifier goes through `tjor_safeprint`, exactly as denial-log hosts do.
- [Byte count is transport-body size, not decoded text] → Fine for a volume signal; the point is order-of-magnitude visibility to inform a future threshold, not exact character counts.

## Migration Plan

Additive: a new addon hook, one bind-mount + env var in `compose.yaml`, a pre-create + recap block in `bin/tjor`, tests. No config, spec-behavior, or runtime-contract change beyond the new teardown line. Rollback is a plain revert. Patch release.

## Open Questions

- Enforcement (threshold/deny/rate-limit) stays deferred until this observability produces real volumes to choose from — the explicit #50 position. This change is the data-gathering step, not that decision.
