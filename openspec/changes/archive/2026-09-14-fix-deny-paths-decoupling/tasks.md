## 1. Decouple deny_paths from mask_dotenv (bin/tjor)

- [x] 1.1 In `run_agent`, hoist the `masked` map and the `deny_paths` block out of the `mask_dotenv != false` conditional so only the automatic dotenv discovery stays gated; keep dedupe between the two intact. Verify: `bash -n` + shellcheck clean; with default config a launch still announces dotenv masks (no behavior change).

## 2. Regression test

- [x] 2.1 Add a case to `tests/integration/landlock_test.sh`: with a scoped `XDG_CONFIG_HOME` config setting `[landlock] mask_dotenv = false` and `deny_paths = ["<repo>/denyme.txt"]`, launch a one-shot session and assert stderr announces `dotenv mask <repo>/denyme.txt (deny_paths)` and does NOT announce a mask for `<repo>/.env`. Verify: test green on the fix; reverting task 1.1 makes it fail.
