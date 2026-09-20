# Tasks

## 1. The detector (python/tjor_secrets.py)

- [x] 1.1 Add a stdlib-only detector: `redact(text) -> str` replacing known secret shapes (AWS `AKIA/ASIA`+16, GitHub `ghp_/gho_/ghs_/ghr_/github_pat_`, Slack `xox[baprs]-…`, Google `AIza…`, PEM `-----BEGIN … PRIVATE KEY----- … -----END … PRIVATE KEY-----` whole block) with `[redacted:<kind>]`; plus `contains_secret(text) -> bool`. Conservative — no entropy/generic-high-value matching; verify via task 3
- [x] 1.2 A tiny CLI (`redact` on stdin→stdout) for shell/manual use, matching the `tjor_*.py` `_main` convention; verify it round-trips a piped secret to a placeholder

## 2. Wire the proof sink + ship in the image

- [x] 2.1 In `proxy/addon.py` `_log_denial`, pass the recorded (attacker-influenced) content through `tjor_secrets.redact()` before `_safe_ascii`, so a secret in a denial-log value is redacted; keep it fail-safe (redaction must never break logging); verify via task 3.2
- [x] 2.2 Add `python/tjor_secrets.py` to the proxy Dockerfile `COPY` so the addon's import resolves in the image; verify the COPY lists it

## 3. Tests (python/tests/test_secrets.py)

- [x] 3.1 Each pattern is redacted (one case per kind, incl. a full PEM block and multiple secrets in one string); **false-positive guards**: a UUID, a 40-hex git SHA, a base64 blob that isn't a known shape, and ordinary prose are returned UNCHANGED; empty/no-match returns unchanged; `contains_secret` agrees with `redact`; verify `pytest python/tests/test_secrets.py` passes
- [x] 3.2 Denial-log proof: a planted secret in a recorded value is redacted in the written denial-log line (drive `_log_denial` with a `DENIAL_LOG` tmp file), while a normal host is unchanged

## 4. The ADR (docs/decisions/0010-secret-scrubbing.md)

- [x] 4.1 Write the ADR (repo format: `# ADR 0010 — …`, Date/Status, `## Decisions`): the discovered-secret risk model; the three boundaries considered (tjor-persisted output/logs, egress inference/gateway stream, harness memory) with why each is in/out of the first increment; the conservative known-shape detection + false-positive stance; the placeholder contract; and an explicit caution that the egress boundary is a separate careful design (evasion, prompt-corruption, latency). Status: accepted (for this increment). Reference #6

## 5. Changelog + follow-ups

- [x] 5.1 CHANGELOG entry under `[Unreleased]` (Added/Security) describing the ADR + detector + denial-log proof wiring, referencing #6 and noting the deferred boundaries
- [x] 5.2 File follow-up issues for the deferred boundaries the ADR names (egress inference/gateway request-body scanning; harness memory/summary scrubbing), so they're tracked

## 6. Full verification

- [x] 6.1 Run the full local gate — `pytest python/tests/` (mitmproxy installed), `tests/doc_consistency.sh`, and `openspec validate secret-scrubbing-adr-and-detector` — and verify everything is green
