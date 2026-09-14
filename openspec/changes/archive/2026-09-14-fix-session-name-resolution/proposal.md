## Why

tjor's own messages display fully-qualified session ids (`<repo>-<hash8>[-<name>]`), but `--session` only accepts the short name: `resolve_session()` unconditionally re-prepends the workspace prefix to whatever it is given. A user who pastes the displayed id into `tjor down --session <qualified-id>` silently constructs a doubled phantom id, tears down a session that never existed, and leaves the real (possibly stuck) session running (#52). The hash prefix is also cwd-derived, so teardown only resolves correctly from the original launch directory, and there is no way to name a session from elsewhere. This cost a real user an orphaned session plus a phantom one while recovering from #51.

## What Changes

- `--session` values are canonicalized instead of blindly prefixed:
  - A value equal to this workspace's qualified id (or prefixed by it) is accepted idempotently — never doubled.
  - A value matching the qualified-id shape that names an *existing* session of another workspace is honored verbatim by lifecycle commands (`down`, `status`, `denials`, `reset`), making them workspace-independent; `tjor run` refuses it loudly (launching this workspace into another workspace's identity would be identity confusion).
  - A qualified-*looking* value with no existing session behind it falls back to short-name behavior with a notice (so an unusual but legitimate short name still works).
- `tjor attach` accepts the short name in addition to the full id.
- `tjor down` reports when nothing matched (no containers, no state dir) instead of silently "succeeding" against a phantom.
- The already-running collision message shows only paste-safe invocations (attach + down), which the resolver changes above guarantee.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `session-lifecycle`: new requirement — session references given to lifecycle commands SHALL resolve unambiguously (short names and fully-qualified ids both accepted, idempotently; nonexistent-target teardown reported); "Reattachment" modified to accept short names.
- `session-launch`: "Named session derivation" modified — derivation SHALL be idempotent for already-qualified values and SHALL refuse another workspace's qualified id at launch.

## Impact

- `bin/tjor`: `resolve_session()` (canonicalization + a small shared base-id helper), `cmd_attach` (short-name match), `cmd_down` (no-match report), the `cmd_run` collision-guard message.
- `tests/integration/lifecycle_test.sh`: regression cases for the exact footgun (pasting the qualified id, teardown from a different cwd, refusing a foreign id at launch, attach by short name).
- No topology, image, proxy, or policy changes; session-id derivation for genuinely-short names is byte-for-byte unchanged (existing sessions unaffected).
