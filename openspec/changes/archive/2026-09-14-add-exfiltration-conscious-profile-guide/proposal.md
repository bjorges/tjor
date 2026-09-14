## Why

Read-only Kubernetes investigation profiles want `pods/log` — the most useful read verb, and the most likely to pull sensitive customer data (PII, accidentally-logged secrets) into a session (#50). Once read, nothing today makes it *hard* for that content to leave: any allowed egress host is a potential sink, and the trade-off isn't documented anywhere, so granting log access silently reads as safe. The issue explicitly asks for (a) exfiltration-conscious egress guidance/tooling, (b) a considered position on log-volume friction (open design question), and (c) the residual risk documented as a conscious choice.

## What Changes

- A new operator guide, `docs/investigation-profiles.md`: the exfiltration-conscious checklist for log-granting profiles — strict-allow minimal egress (API origin + inference only), no content-sink hosts, teardown denial-recap review (#42), RBAC posture (view-only, no `secrets get`, `pods/log` as a named conscious grant), short token TTL — plus a worked policy/config example and an explicit residual-risk statement (the model provider is itself an allowed content sink; egress policy cannot un-read what entered the context).
- README's kube-broker section points to the guide whenever `pods/log` is granted.
- `tests/doc_consistency.sh` gains a structural check: the guide exists and the README references it (same drift-catching pattern as the shipped/roadmap invariant).
- The log-volume friction idea (size/rate limits on `pods/log` responses at the proxy) is analyzed and **deliberately deferred** in this change's design doc — it is implementable (the log stream transits the proxy) but needs an operator decision on thresholds/streaming semantics before it can be specced honestly.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `credential-broker`: new requirement — granting log access is documented as a conscious exfiltration trade-off (shipped guide + README pointer), never an assumed-safe default.

## Impact

- `docs/investigation-profiles.md` (new), `README.md` (kube section pointer), `tests/doc_consistency.sh` (existence/reference check).
- No runtime behavior changes; the volume-friction mechanism is explicitly out of scope pending design input (recorded in design.md).
