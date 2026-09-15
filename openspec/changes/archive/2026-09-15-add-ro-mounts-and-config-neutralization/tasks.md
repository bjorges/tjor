# Tasks — read-only mounts + untrusted project-config neutralization

## 1. --dir-ro (issue #44)

- [x] 1.1 `bin/tjor cmd_run`: parse repeatable `--dir-ro`, resolve/dedupe into
      `TJOR_EXTRA_DIRS_RO` with the same existence + sensitive-path checks as
      `--dir` (message states read-only exposure), and die on a path present
      in both lists. Verify: launching with a nonexistent/sensitive/conflicting
      path aborts with the right message (multirepo_test.sh checks).
- [x] 1.2 `bin/tjor run_agent`: mount RO extras `:ro`, include them in
      `safe[]` (git trust + mask discovery), announce as read-only, and pass
      newline-delimited `TJOR_RO_DIRS` via `compose run -e`. Document at the
      definition site that `TJOR_SAFE_DIRS`+`TJOR_RO_DIRS` are the durable
      in-container contract of operator-approved roots and their writability
      class, which the future #53 dynamic-trust helper consumes (dynamic
      trust may only grow under writable roots). Verify: probe in
      multirepo_test.sh reads OK / write refused inside the RO mount; the
      contract comment is present at the TJOR_SAFE_DIRS build site.
- [x] 1.3 `images/agent/entrypoint.sh` step 6: grant `--allow-read` (not
      `--allow-write`) for wrap dirs listed in `TJOR_RO_DIRS`. Verify:
      shellcheck clean; on a Landlock engine the multirepo probe write into
      the RO mount fails and reads succeed (container `:ro` already enforces;
      kernel agreement asserted where the engine supports it).
- [x] 1.4 multirepo_test.sh: new `--dir-ro` section — read OK, write/delete
      refused, `git status` works, `.env` inside the RO repo masked,
      `--dir`+`--dir-ro` same-path conflict dies. Verify: test passes.

## 2. mask_dirs (issue #43)

- [x] 2.1 `config/tjor.toml`: add `mask_dirs = []` with comments (semantics,
      recommended hardened value, mid-session residual). Verify:
      `tjor_cfg check` accepts a user config setting `mask_dirs` (shape) and
      test_cfg/test_config_ergonomics cover it.
- [x] 2.2 `bin/tjor run_agent`: validate + apply `mask_dirs` — entries via a
      python filter (absolute or bare-name, no newline, else die); absolute →
      mask if dir exists (warn if not, mirroring deny_paths); name → NUL-safe
      `find -type d -name` over every mounted tree (`.git` pruned); bind the
      freshly recreated `${TJOR_SESSION_DIR}/mask-empty` `:ro` over each,
      dedupe via `masked[]`, announce via `safeprint`, independent of
      `mask_dotenv`. Verify: landlock_test.sh new section.
- [x] 2.3 landlock_test.sh: mask_dirs section (mode=off launch, works on any
      engine) — plant `.opencode/plugins/evil.js` + nested `sub/.opencode/`,
      config `mask_dirs=[".opencode"]` with `mask_dotenv=false` (proves
      independence), probe asserts: both dirs list empty in-cage, write into
      mask refused, announcements present (escape-sanitized path check with a
      hostile dir name), invalid entry (`foo/bar`) aborts the launch.
      Verify: test passes end-to-end.

## 3. Managed opencode config (issue #46)

- [x] 3.1 `python/tjor_profile.py`: add `managed` to `ALLOWED` (docstring:
      consumed by the entrypoint managed tier, not overlaid). Verify:
      test_profile.py stages `managed/opencode.json`, still filters
      credentials inside it, and non-managed behavior unchanged.
- [x] 3.2 `bin/tjor prepare_profile`: after staging, if
      `profile/managed/opencode.json` exists and is not valid JSON, die
      naming the file. Verify: profile_test.sh invalid-JSON launch aborts.
- [x] 3.3 `images/agent/entrypoint.sh` (root phase, new step): staged managed
      file → validate JSON (exit 90 on failure), install to
      `/etc/opencode/opencode.json` root:root 0644 (dir 0755); no staged file
      → remove any stale managed file. Exclude `managed/` from the
      per-harness overlay loop (like `instructions/AGENTS.md`). Verify:
      profile_test.sh assertions.
- [x] 3.4 profile_test.sh: managed section — file present root-owned with
      exact content, agent user cannot write/replace/remove it, `managed/`
      absent from `~/.config/opencode/`, relaunch without profile removes the
      managed file, invalid JSON refuses launch. Verify: test passes.

## 4. Docs + verification sweep

- [x] 4.1 README: `--dir-ro` in usage/flags, `mask_dirs` under the landlock
      config docs (with residuals stated), managed profile tier under
      profiles; config/tjor.toml comments final. Verify:
      tests/doc_consistency.sh passes.
- [x] 4.2 CHANGELOG `[Unreleased]`: three entries (Added), each naming its
      issue and the enforcement point. Verify: entries match shipped
      behavior claims exactly (review discipline).
- [x] 4.3 Full sweep: python suite, shellcheck on changed shell files, and
      the touched integration tests (multirepo, landlock, profile) green on
      the live engine. Verify: all pass locally.
