# Tasks

## 1. Launcher: the self-mount guard

- [x] 1.1 Add `self_mount_overlaps()` (`$1` = a root; true when `TJOR_ROOT` equals, lies under, or contains it on component boundaries) and, in `cmd_run` after the cross-class overlap check and before `resolve_agent_image`, refuse any writable root it overlaps with `die`, naming `TJOR_ROOT`, the root, and the three remedies (design D1/D2). Verify: `bash -n bin/tjor` and the 5.1 refusal checks
- [x] 1.2 Parse `--allow-self-mount` in `cmd_run`; export `TJOR_ALLOW_SELF_MOUNT=1`; on an actual override print one `warn` naming the tree; for a read-only overlap (`TJOR_EXTRA_DIRS_RO`) print one notice line and continue (design D3). Verify: 5.1 override + notice checks
- [x] 1.3 Update `usage` (run line: `[--allow-self-mount]`, and a clause "the running tjor tree is refused as a writable mount unless --allow-self-mount"). Verify: `bin/tjor help` grep in 5.4; `shellcheck --severity=warning bin/tjor` clean

## 2. Self-install and the source-tree marker

- [x] 2.1 Add `is_source_tree()` (`.git` dir or `.tjor-source-sha` file under `TJOR_ROOT`) and switch `resolve_agent_image`'s pull condition to `! is_source_tree` (design D5). Verify: 5.2 asserts a marker-only tree takes the build path (shimmed docker records `build`, never `pull`)
- [x] 2.2 Add `cmd_self_install [--ref <commit-ish>]`: require `.git`; resolve the sha; install root `${TJOR_INSTALL_ROOT:-$HOME/.tjor/install}`; if `<root>/<sha>` exists report "already installed" and only repoint `current`; else `git archive` into a temp dir under the root, write `.tjor-source-sha`, `chmod -R a-w`, atomic `mv`; `ln -sfn <sha> <root>/current`; print the launcher path and, when a previous different `current` existed, `git log --oneline <prev>..<sha>`; state that uncommitted changes are excluded (design D4). Wire into `main` and `usage`. Verify: 5.2 tree checks (marker, non-writable, `current`, idempotence, not-a-checkout error)
- [x] 2.3 Add the install root as the third root in `init_sensitive_roots` / `dir_is_sensitive` (design D7); extend the `--unsafe-dir` help wording if needed. Verify: 5.3 asserts `--dir <install root>` and a workspace under it are refused, and `${TJOR_INSTALL_ROOT}` is honored

## 3. Image provenance label

- [x] 3.1 Add `source_sha()` (marker → sha; `.git` → `git rev-parse HEAD` + `-dirty` when `git status --porcelain` is non-empty; else `release-<VERSION>`) and pass `--label tjor.source-sha="$(source_sha)"` to `build_proxy`, `build_agent`, `build_conformance` (design D6). Verify: 5.2 label check via the recording docker shim; `shellcheck` clean

## 4. Doctor report

- [x] 4.1 In `cmd_doctor`, replace the bare root line with the root kind (mutable git checkout | self-installed `<sha>`, read-only | installed release `<VERSION>`), and for a checkout warn when the would-be workspace from cwd (`git rev-parse --show-toplevel`, else `pwd -P`) overlaps `TJOR_ROOT` per `self_mount_overlaps`, naming `tjor self-install` (design D8). Must succeed outside any repository. Verify: 5.4 doctor checks

## 5. Launcher test (daemon-free, `unit` job)

- [x] 5.1 Create `tests/integration/self_mount_test.sh` (pattern: `workspace_gate_test.sh` — source `bin/tjor`, temp `HOME` under `~/.tjor/tmp`, `GIT_CEILING_DIRECTORIES`, docker shim that records argv and exits 1, custom `session.root`; `TJOR_ROOT` is the real checkout): refusals for workspace = checkout, `--dir <checkout>/images`, `--dir <parent of checkout>`; `--allow-self-mount` proceeds with the warning; `--dir-ro <checkout>` proceeds with the notice and no refusal; an ordinary repo with no overlap prints no self-mount text; refusals never reach docker (`check "…"` names literal — they feed the matrix). Verify: `bash tests/integration/self_mount_test.sh` passes
- [x] 5.2 Add self-install checks with `TJOR_INSTALL_ROOT=$WORK/install`: `cmd_self_install` (HEAD) creates `<sha>/` with `bin/tjor`, `compose.yaml`, `config/`, `python/`, `images/`, `VERSION`, `.tjor-source-sha` = sha; no writable file or dir under it; `current` → sha; second run reports already installed; `--ref` of a bogus name fails; from the installed tree (`TJOR_ROOT` re-pointed in a subshell) `is_source_tree` is true, `source_sha` = sha, and `resolve_agent_image` with the shim records `build` and no `pull`; `build_agent` argv carries `--label tjor.source-sha=<sha>`; from the checkout `source_sha` is `HEAD` (+`-dirty` if dirty). Verify: `check` lines pass
- [x] 5.3 Add install-root sensitivity checks: `dir_is_sensitive` true for the install root, a dir under it, and its parent; `--dir <install root>` refused; a workspace under it refused. Verify: `check` lines pass
- [x] 5.4 Add doctor checks (docker shim makes `report_tiers` degrade): from inside the checkout the output names a mutable git checkout and warns about launching from here; from an installed tree it names the sha, read-only, no warning; from a non-repo dir it succeeds. Add the help-text grep. Verify: `check` lines pass
- [x] 5.5 Wire the test into the `unit` CI job as `launcher self-mount guard + self-install (no docker) (#67)`; `shellcheck --severity=warning tests/integration/self_mount_test.sh` clean. Verify: step present; YAML parses

## 6. Boundary matrix + docs

- [x] 6.1 `python/gen_boundary_matrix.py`: `SELF_MOUNT = "self-mount"`, `SELF_MOUNT_FILE`, include in `parsed_names()`; REGISTRY entries for every check name — rendered rows under a new `launcher-integrity` capability (add it to `CAPABILITY_ORDER`): the three writable-overlap refusals and "The install root is refused as a mount" (session-launch); the rest `boundary=False`. Regenerate `docs/boundary-matrix.md`. Verify: `python3 python/gen_boundary_matrix.py --check` clean; `tests/doc_consistency.sh` passes
- [x] 6.2 README: in the install/trust section, state that the running tjor tree is refused as a writable mount, the read-only and `--allow-self-mount` alternatives, and `tjor self-install` for developing tjor inside tjor; INSTALL.md: a short "Developing tjor inside tjor" subsection with the three commands. Verify: `tests/doc_consistency.sh` passes and the text reads correctly
- [x] 6.3 ADR 0008: an "Amended (#67)" paragraph — decision 1 now reads "a source tree (git checkout or self-installed tree) always builds locally"; images carry `tjor.source-sha`. Verify: paragraph present
- [x] 6.4 CHANGELOG `[Unreleased]` — Security, **BREAKING**: the self-mount refusal (+ override, read-only notice), `tjor self-install`, the install root in the sensitive set, marker-driven local builds, the `tjor.source-sha` label, the doctor report, and the honest scoping of the doctor clause. Verify: entry present and references #67

## 7. Verification

- [x] 7.1 Full local gate: `bash tests/integration/self_mount_test.sh`, `bash tests/integration/workspace_gate_test.sh`, `uvx --python 3.14 --with 'mitmproxy==12.1.2' pytest python/tests -q`, `tests/doc_consistency.sh`, `shellcheck --severity=warning bin/tjor tests/integration/*.sh`, `npx --yes @fission-ai/openspec@latest validate launcher-self-mount-guard`. Verify: all green
- [x] 7.2 Manual end-to-end on a real engine (**observed 2026-09-27 on colima, macOS**: `./bin/tjor run -- true` from this checkout refused with exit 1 naming the tree and the remedies; `./bin/tjor self-install` installed HEAD 6d1adc1 read-only with the marker and 0 writable entries; `tjor doctor` from the checkout printed `git checkout — MUTABLE` plus the launch-from-here warning; a launch from the installed tree with the checkout as workspace ran a one-shot command (exit 0) and `down` cleaned up. The installed tree was v0.19.0 code, pre-fix, so its own doctor line and label were not exercised live — the shimmed test covers those): from this checkout `tjor run -- true` is refused; `tjor self-install` then `~/.tjor/install/current/bin/tjor run -- true` from the checkout launches and builds locally (image labeled with the sha, `docker image inspect`); `tjor doctor` from both trees prints the expected root line. Verify: observations recorded in tasks.md
