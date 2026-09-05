# Tasks: add-multi-repo

## 1. Launcher

- [x] 1.1 Parse repeatable `--dir <path>` in `cmd_run` into an array; resolve each to an absolute path — verified by the integration test's two-repo launch
- [x] 1.2 Verify each extra dir exists and is VM-shared (reuse `verify_bind_source`); abort with the offending path named — verified by an integration case with a nonexistent dir
- [x] 1.3 Pass each extra dir to the agent as a same-path writable mount (`compose run --volume host:host`); primary workspace and session id unchanged — verified in-cage: both repos present at host paths, writable, git works

## 2. Docs & test

- [x] 2.1 Usage line + README note for `--dir` — verified against implemented behavior
- [x] 2.2 `tests/integration/multirepo_test.sh`: launch one session over two repos, assert both mounted at host paths, both writable, git status works in each, and a nonexistent `--dir` aborts; CI job — verified green locally and on the Linux engine
