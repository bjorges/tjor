# Proposal

## Why

Read-only Kubernetes investigation profiles often grant `pods/log` (via the `view` ClusterRole), one of the most useful read verbs — and one of the most likely to pull sensitive customer data (PII, accidentally-logged secrets) into the model context (#50). The concrete controls already shipped: an exfiltration-conscious profile guide, view-minus-secrets RBAC guidance, strict-allow egress, and the residual-risk statement (v0.14-era work). The one open item from #50's design review was **log-volume friction**, and it was deliberately deferred with a recorded recommendation: *observability before enforcement*. A byte/rate threshold needs operator decisions we should not guess (legitimate investigations read megabytes; `follow=true` streaming complicates counting; deny-mid-read corrupts a `kubectl` invocation). The honest first step is to **produce the data** that makes a real threshold choosable — a per-session count of how much workload-log content was actually read — without changing any control or breaking any workflow. The maintainer's proposal on #50 ("observability first, enforcement later") is exactly this increment.

## What Changes

- **The proxy counts workload-log read volume per session.** For responses to the Kubernetes log endpoint (`/api/v1/namespaces/<ns>/pods/<pod>/log`) on a configured cluster API host, the addon accumulates response body bytes, keyed by pod, to a session-owned counter file — mirroring how the denial log (#23) is wired (a bind-mounted, bounded, fail-safe file). Counting is streaming-aware so `follow=true`/large-body reads are still counted, and it **never** alters, blocks, or delays the response (observability only).
- **`tjor down` surfaces it in the denial recap (#42).** Teardown already recaps denied egress; it gains one line when any workload-log content was read: e.g. `tjor: this session read 42.7 MB of workload logs across 6 pod(s) — review what left the session with 'tjor denials'`. Quiet when none was read. Pod identifiers are attacker-influenced and rendered through the existing terminal-escape sanitizer.
- **No enforcement.** No threshold, no deny, no rate limit, no config surface. The recorded position stays: enforcement is specced later, if ever, once real numbers exist.

## Capabilities

### Modified Capabilities

- `credential-broker`: adds a requirement that a session's workload-log read volume is observable — counted at the proxy and surfaced at teardown — as the observability half of the existing "Log access is a documented, conscious trade-off" requirement. No change to credential handling.

## Impact

- **Code**: `proxy/addon.py` (a streaming-aware response hook that counts `pods/log` bytes for kube API hosts and writes a bounded per-pod counter file, fail-safe); `compose.yaml` (bind-mount the counter file + set its env var, mirroring `TJOR_DENIAL_LOG`); `bin/tjor` (`cmd_down` recap reads and aggregates the counter file into one line; pre-create the file like `denials.log`).
- **Tests**: `python/tests/` (the addon counts only matching `pods/log` paths on kube API hosts, ignores other traffic, is streaming-aware, and never mutates the response; counting is fail-safe); a `bin/tjor`/integration check that the recap line renders and sanitizes pod names.
- **Behavior change**: teardown reports workload-log read volume when a session read any; nothing else changes — no egress control, no request altered, no new failure mode (counting is best-effort like denial logging). Establishes the observability baseline for #50; enforcement remains deferred.
