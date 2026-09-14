## Context

See proposal.md — Why. What already exists and shapes this: strict-allow per-profile policies (trusted `.tjor/policy.toml`), the kube broker with origin-scoped injection (#49) and the scoped SSRF exemption (#45), the denial recap at teardown (#42), and the LLM gateway (D4) that concentrates inference egress onto one host. The missing piece is the *posture*: which combination of those to use when a profile grants `pods/log`, and an honest statement of what none of them can prevent.

## Goals / Non-Goals

**Goals:**
- One canonical, checklist-shaped document an operator can follow before trusting a log-granting profile against a production cluster.
- The residual risk stated plainly enough that granting `pods/log` is always a conscious act.
- A recorded, reviewable position on the log-volume-friction question so it stops being an unexamined "maybe".

**Non-Goals (this change):**
- Implementing log-volume limits, redaction, or content inspection (see Decisions 3).
- New config surface or proxy behavior.

## Decisions

1. **Guide as a shipped doc (`docs/investigation-profiles.md`), enforced by doc-consistency lint** rather than README-only prose: the README section stays short (its style), the guide can carry a worked policy, and the lint prevents the pointer and the doc from drifting apart — the same failure class the existing shipped/roadmap check catches.
2. **The checklist leans on existing mechanisms, in priority order**: (a) strict-allow egress with ONLY the API origin + the inference path (gateway host, or the provider API when gateway-less) — nowhere for content to go is the strongest available control; (b) RBAC: `view`-minus-`secrets`, `pods/log` named explicitly; (c) short `kube_duration`; (d) review the #42 recap at teardown — denied egress during an investigation session is a signal, not noise. This is deliberately guidance-over-mechanism: every item is enforceable today.
3. **Log-volume friction: analyzed, deferred.** The `pods/log` response transits the proxy (the API origin is MITM'd), so a byte/rate threshold per session on paths matching `/api/v1/namespaces/*/pods/*/log` is implementable at the addon. Deferred because the honest spec needs operator decisions we should not guess: threshold values (a normal investigation legitimately reads megabytes), semantics for `follow=true` streams (mitmproxy streams large bodies — `stream_large_bodies=1m` — so counting needs stream-aware hooks), and the failure mode (warn vs deny mid-read can corrupt a kubectl invocation). Recommendation recorded here: if friction is wanted, start with *observability* (a per-session log-bytes counter surfaced in the #42 recap), not enforcement — it produces the data that makes a real threshold choosable. Revisit on #50 with that proposal.
4. **Residual risk is stated as unavoidable, not mitigated-away**: with inference egress allowed (the point of the session), log content that enters the model context reaches the model provider by design; and no egress control can un-read content into a human-visible transcript. The guide says exactly this, so the "include pods/log, make exfiltration difficult" requirement lands as: *difficult everywhere except the sinks you consciously chose*.

## Risks / Trade-offs

- [Guidance can be ignored] → the doc-consistency lint keeps it discoverable from the README's kube section; the #42 recap gives a per-session behavioral nudge regardless.
- [A worked example policy can go stale] → it names only structural hosts (API origin placeholder + gateway host), not provider-of-the-day endpoints.

## Migration Plan

Docs + lint only; nothing to migrate or roll back.

## Open Questions

- Log-volume observability/enforcement (decision 3): follow-up on #50 once the counter proposal is accepted or rejected by the operator.
