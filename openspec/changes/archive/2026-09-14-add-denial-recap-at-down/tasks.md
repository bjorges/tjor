## 1. Recap at teardown

- [x] 1.1 `bin/tjor` `cmd_down`: after teardown, when `denials.log` is non-empty, aggregate (count + top hosts) in python and print the recap + hints to stderr, hosts sanitized via `tjor_safeprint.sanitize`; skip the log's cap-notice line. Verify: shellcheck clean; recap appears after a real denial, absent on an empty log.

## 2. Tests

- [x] 2.1 `tests/integration/ergonomics_test.sh`: after the existing real-denial check, `tjor down` output contains the recap (count + `blocked-example-xyz.test` + policy-add hint); then truncate the log and a second `tjor down` prints no recap. Verify: test green.

## 3. Docs

- [x] 3.1 CHANGELOG entry under Unreleased (#42). Verify: entry present, style-consistent.
