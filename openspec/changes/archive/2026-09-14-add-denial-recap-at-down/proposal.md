## Why

`tjor denials` surfaces blocked egress only if the operator remembers to run it (#42). A session that quietly hit the allowlist wall gives no signal at the moment the operator is most likely to notice: teardown. This also underpins the exfiltration-conscious posture (#50) — session-end egress feedback is how a minimal-hosts profile stays minimal *and* how unexpected exfiltration attempts become visible.

## What Changes

- `tjor down` automatically prints a short denial recap when the session's denial log is non-empty: total denied attempts, the top denied hosts with counts, and the `tjor denials` / `tjor policy add` hints. Quiet when there were no denials.
- Hostnames are attacker-influenced: aggregation happens in python and every host renders through the shared terminal-escape sanitizer (`tjor_safeprint.sanitize`) — same defense as `tjor denials`.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `policy-ergonomics`: new requirement — teardown surfaces a sanitized denial recap unprompted; silent when the session had no denials.

## Impact

- `bin/tjor` (`cmd_down`); `tests/integration/ergonomics_test.sh` (recap present after a real denial; quiet after truncating the log). No proxy, image, or state-format changes (the denial log format is unchanged; the recap is a reader).
