# Tasks

## 1. Detector: name the matched kinds without the value

- [x] 1.1 Add `kinds_present(text) -> list[str]` to `python/tjor_secrets.py`: return the sorted unique kinds whose pattern matches, and **no values**. Total by construction (per-pattern `try/except: continue`, like `redact`/`contains_secret`). Empty/no-match → `[]`

## 2. Proxy: the observe-only tripwire

- [x] 2.1 Add scan config/state in `proxy/addon.py`: `SCAN_HOSTS` (frozenset from `TJOR_SECRET_SCAN_HOSTS`, canonicalized like `KUBE_API_HOSTS`), `SCAN_MAX_BYTES` (from `TJOR_SECRET_SCAN_MAX_BYTES`, default 262144), `SECRET_SCAN_LOG` (from `TJOR_SECRET_SCAN_LOG`) + a bounded line counter/cap (mirror the denial/log-volume state)
- [x] 2.2 Add `_record_secret_scan(host, kinds)` — a fail-safe sink (mirror `_record_log_volume`): append `<safe_host>\t<comma-joined kinds>\n` to `SECRET_SCAN_LOG` when set + under the cap; **never** write the secret value or body; swallow every error
- [x] 2.3 Add `_scan_request_body(flow)` — for an allowed request whose `flow.request.host` is in `SCAN_HOSTS`: read up to `SCAN_MAX_BYTES` of `flow.request.content` (skip if `None`/streamed), run `kinds_present`, and on a non-empty result call `_record_secret_scan`. Reads only — never mutates the body. Entirely wrapped in `try/except Exception: pass`
- [x] 2.4 Call `_scan_request_body(flow)` in the `request` hook's allowed branch (before `return`, after the identity/broker/gateway apply). It MUST be self-guarded so an error can never reach the hook's outer fail-closed guard (would wrongly deny a legitimate inference request — the v0.18.9 lesson)

## 3. Config + wiring

- [x] 3.1 `config/tjor.toml`: a `[secrets]` block — `scan_hosts = []` (gateway-less inference hosts to scan; the gateway host is auto-added when enabled) and `scan_max_bytes = 262144`, with comments (best-effort accidental-leak tripwire; not a guarantee)
- [x] 3.2 `bin/tjor`: export `TJOR_SECRET_SCAN_HOSTS` (from `[secrets] scan_hosts`, plus the gateway host when the gateway is enabled), `TJOR_SECRET_SCAN_MAX_BYTES`, and `TJOR_SECRET_SCAN_LOG`; pre-create the signal file (like `denials.log` / `logvolume.log`)
- [x] 3.3 `compose.yaml`: set `TJOR_SECRET_SCAN_HOSTS` / `TJOR_SECRET_SCAN_MAX_BYTES` / `TJOR_SECRET_SCAN_LOG` on the proxy and bind-mount the signal file, mirroring the denial/log-volume wiring
- [x] 3.4 `bin/tjor` `cmd_down`: after the existing recaps, when the scan-log is non-empty, aggregate it (count of requests, distinct kinds) and print one honest line — "sent N inference request(s) containing what looked like a discovered secret (kinds: …) — best-effort tripwire; content reaches allowed egress by design"; quiet when empty

## 4. The ADR

- [x] 4.1 Write `docs/decisions/0011-egress-secret-tripwire.md` (repo ADR format, building on 0010, referencing #62): the observe-only tripwire decision; the match→action contract (signal, never alter/block); scope (inference/scan hosts); the bounded-scan latency stance; the evasion stance (best-effort, explicitly NOT a guarantee — trivially evadable); why the signal never carries the value; and that enforcement (redact/block) is deferred. Status: accepted

## 5. Tests

- [x] 5.1 `python/tests/test_secrets.py`: `kinds_present` returns the right kinds for single/multiple shapes, `[]` for benign/empty, is total on pathological input, and never returns a value
- [x] 5.2 Addon tests (`python/tests/`): a request to a scan-host with a secret-shaped body records count+kinds AND the body is forwarded byte-for-byte unchanged; a request to a non-scan-host is not scanned; the scan is bounded to `SCAN_MAX_BYTES`; a streamed/`None` body is forwarded unscanned; the scan is fail-safe — a raising `kinds_present`/sink does NOT raise and does NOT deny the request (assert `flow.response` stays `None`)
- [x] 5.3 Recap aggregation test: a scan-log with several entries aggregates to the expected request count + distinct kinds; the secret value never appears

## 6. Verification

- [x] 6.1 CHANGELOG `[Unreleased]` (Added/Security): the egress inference-body tripwire (observe-only, best-effort, surfaced at teardown), referencing #62/#6 and ADR 0011; note it is explicitly not a guarantee and enforcement stays deferred
- [x] 6.2 Full local gate: `pytest python/tests/`, `tests/doc_consistency.sh`, `shellcheck bin/tjor`, `openspec validate egress-secret-tripwire`; note the live inference-path exercise is CI/manual (no local Docker)
