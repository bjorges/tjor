## 1. Launcher fix (bin/tjor run_agent)

- [x] 1.1 In `run_agent()`, force PTY allocation on the agent container: add `-T=false` to the `compose run -d` invocation when `[[ -t 0 ]]`, with a comment explaining the command-substitution/auto-detection trap. Verify: from a terminal, `docker inspect -f '{{.Config.Tty}}'` on a fresh session's agent container prints `true` (shellcheck stays clean).
- [x] 1.2 Add post-create verification: when the force was applied, inspect the created container's `.Config.Tty` and `die` with a clear message if it is not `true`. Verify: temporarily inverting the check makes `tjor run` abort with the new message; restored check passes.
- [x] 1.3 Add the loud non-terminal warning: when stdin is not a terminal, warn that the session has no PTY and interactive harnesses will not work (both attach and `--detach` paths); one-shot commands unchanged. Verify: `echo | tjor run --session t -- true` prints the warning and exits 0.

## 2. Real-PTY integration test

- [x] 2.1 Create `tests/integration/tty_test.sh` with a `run_pty` helper covering BSD and util-linux `script(1)` syntax (command written to a temp script file), following the existing integration-test structure (ok/bad/check, cleanup trap, session teardown). Verify: the file passes shellcheck and runs green locally.
- [x] 2.2 Probe A — startup TTY: under `run_pty`, launch `tjor run --session <name> -- sh -c '[ -t 0 ] && [ -t 1 ]'`; assert exit code 0 and the agent container's `Config.Tty=true`. Verify: test passes on the fixed code; stashing the fix (removing `-T=false`) makes it fail.
- [x] 2.3 Probe B — interactive input through attach: probe prints `READY`, reads a line, exits 0 only on the expected value; feeder waits for `READY` in `docker logs` before writing the line into the PTY. Verify: test passes repeatably (3 consecutive runs).
- [x] 2.4 Probe C — non-terminal degradation: without a PTY, `tjor run --session <name> -- sh -c 'exit 7'` propagates exit code 7 and stderr contains the no-PTY warning. Verify: assertions pass.

## 3. CI + docs

- [x] 3.1 Add a CI job (or extend an existing one) in `.github/workflows/ci.yml` running `tests/integration/tty_test.sh`, following the existing integration-job pattern. Verify: job is wired the same way as lifecycle's (bash invocation, image prebuild if the pattern requires it).
- [x] 3.2 Update CHANGELOG.md under the unreleased/next section describing the fix (#51). Verify: entry present and consistent with the repo's changelog style.
