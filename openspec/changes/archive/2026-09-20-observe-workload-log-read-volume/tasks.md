# Tasks

## 1. Proxy: count workload-log read volume

- [x] 1.1 In `proxy/addon.py`, add module state mirroring the denial log: `LOG_VOLUME_LOG = os.environ.get("TJOR_LOG_VOLUME_LOG", "")`, a line-count guard, and a cap constant (reuse the `_DENIAL_LOG_MAX` style)
- [x] 1.2 Add a compiled matcher for the log endpoint: `^/api/v1/namespaces/[^/]+/pods/[^/]+/log`, capturing the pod name; a helper that returns the pod name for a matching (host in `KUBE_API_HOSTS`, path) request or `None`
- [x] 1.3 Add a `responseheaders` hook: for a matching request (kube broker active, host in `KUBE_API_HOSTS`, path matches), install a counting passthrough on `flow.response.stream` that tallies `len(chunk)`, returns each chunk UNMODIFIED, and on the end-of-stream sentinel (`b""`) flushes the per-pod total. Install nothing for non-matching requests
- [x] 1.4 Add `_log_log_volume(pod, nbytes)` that appends `pod\tbytes\n` to `LOG_VOLUME_LOG` when set and under the cap (with a one-line cap notice at the cap), fail-safe — swallow every error (must never raise into the proxy). The stream passthrough must return the original chunk even if tallying/flush throws

## 2. Wire the counter file (compose)

- [x] 2.1 In `compose.yaml`, set `TJOR_LOG_VOLUME_LOG: /logvolume.log` on the proxy and bind-mount `${TJOR_SESSION_DIR:?}/logvolume.log:/logvolume.log`, mirroring the `denials.log` wiring

## 3. Surface at teardown (bin/tjor)

- [x] 3.1 In `bin/tjor`, pre-create `${TJOR_SESSION_DIR}/logvolume.log` where `denials.log` is pre-created (bind source must exist; accumulates across the session)
- [x] 3.2 In `cmd_down`, after the #42 denial recap, when `logvolume.log` is non-empty aggregate it in python (sum bytes, count distinct pods) and print one stderr line — total volume (human-readable KB/MB/GB) + distinct-pod count + a review hint — rendering any pod identifier through `python/tjor_safeprint.py`; quiet when empty/absent

## 4. Tests

- [x] 4.1 Addon unit tests (`python/tests/`): a matching `pods/log` response on a `KUBE_API_HOSTS` host is counted (per-pod bytes written) and returned unchanged; a streamed/multi-chunk body is fully counted via the passthrough and each chunk is returned identical; a non-log request and a `pods/log` request to a non-kube host are NOT counted; counting is fail-safe (a throwing sink/flush does not raise and the chunk is returned unmodified)
- [x] 4.2 Teardown recap: a `logvolume.log` with several pods aggregates to the expected total + distinct-pod count, and a pod name containing escape bytes is sanitized in the printed line (unit-test the aggregation python, or an integration assertion in the kube suite)

## 5. Changelog + verification

- [x] 5.1 CHANGELOG entry under `[Unreleased]` (Added) describing the per-session workload-log volume counter surfaced at `tjor down`, referencing #50 and noting enforcement stays deferred
- [x] 5.2 Run the full local gate — `pytest python/tests/`, `tests/doc_consistency.sh`, `openspec validate observe-workload-log-read-volume` — and verify green (docker-gated kube integration runs in CI)
