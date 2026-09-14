## 1. Resolver canonicalization (bin/tjor)

- [x] 1.1 Factor the workspace base-id derivation (`<repobase>-<hash8>`) out of `resolve_session()` into a helper reusable by `cmd_attach`. Verify: `bash -n` + shellcheck clean; existing short-name derivation byte-identical (compare a session id before/after on the same workspace).
- [x] 1.2 Implement `--session` canonicalization in `resolve_session()` per design decision 1 (idempotent base/base-prefix acceptance; existing foreign qualified id honored for lifecycle commands with a notice; refused for launch via a launch-mode argument from `session_setup`; qualified-looking-but-nonexistent falls back to short name with a notice). Verify: sourcing `bin/tjor` and driving `resolve_session` through each branch yields the expected `TJOR_SESSION` values.
- [x] 1.3 Update `cmd_run`'s collision-guard message to show paste-safe invocations (attach, `tjor down --session <sid>`, separate `--session <name>`). Verify: message renders each command such that pasting it verbatim works.
- [x] 1.4 Add the `cmd_down` no-match report (warn when neither labeled containers nor a state dir exist; cleanup still runs). Verify: `tjor down --session never-existed` prints the warning and exits 0.
- [x] 1.5 Extend `cmd_attach` to also match the short name (`base-want` and `want == base`) alongside exact full-id matches. Verify: `TJOR_ATTACH_DRY=1 tjor attach <short>` resolves the same container as the full id.

## 2. Regression tests (tests/integration/lifecycle_test.sh)

- [x] 2.1 Add the exact-footgun case: launch a named session, run `tjor down --session <fully-qualified-id>` from the workspace, assert the real session's containers are gone and no doubled (`<base>-<base>-...`) resources were ever created. Verify: test green; reverting task 1.2 makes it fail.
- [x] 2.2 Add cross-cwd teardown: `tjor down --session <qualified-id>` from a different directory tears down the session. Verify: test green.
- [x] 2.3 Add launch refusal: `tjor run --session <foreign-qualified-id>` exits non-zero with the refusal message and creates nothing. Verify: test green.
- [x] 2.4 Add attach-by-short-name (`TJOR_ATTACH_DRY=1`) resolving to the same container as the full id. Verify: test green.

## 3. Docs

- [x] 3.1 Update CHANGELOG.md under the unreleased/next section describing the fix (#52), and adjust the `usage()` text for `--session` if it only mentions short names. Verify: entries present, consistent with repo style.
