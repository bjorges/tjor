# Design

## Context

See proposal.md — Why, and the delta specs. Grounding in `bin/tjor` at v0.19.0 (observed):

- `TJOR_ROOT` is derived once at the top of the script from `realpath(BASH_SOURCE)`'s grandparent (Python, ~L16), so it is already a physical path. Everything host-side executes from it (`cfg`, `tjor_profile.py`, `tjor_trust.py`, `gen_corefile.py`, …) and all three image builds use it as the build context (`build_proxy` ~L97, `build_agent` ~L103, `build_conformance` ~L129).
- `resolve_agent_image` (~L139) decides pull-vs-build on `[[ ! -d "${TJOR_ROOT}/.git" ]]`: no `.git` means "installed copy, may pull". A self-installed tree has no `.git`, so without a marker it would pull a published image for `VERSION` instead of building the source it was made from — the opposite of what a developer expects from a tree they just archived.
- `cmd_run`: the writable roots are final only after the `--dir` / `--dir-ro` loops and the cross-class overlap check (`TJOR_WORKSPACE`, `TJOR_EXTRA_DIRS[@]`; read-only in `TJOR_EXTRA_DIRS_RO[@]`); `resolve_agent_image` runs next, then the first `docker` call.
- `init_sensitive_roots` / `dir_is_sensitive` (v0.19.0, #64) already hold two tjor-owned roots with symmetric containment; adding a third is one line each. `--unsafe-dir` is their override.
- `cmd_doctor` prints `tjor root: ${TJOR_ROOT}` and runs `report_tiers` (which calls `docker info`); it does not need a repository.
- Tests: `tests/integration/workspace_gate_test.sh` is the pattern — source `bin/tjor`, temp `HOME` under the real `~/.tjor/tmp` (a macOS `mktemp` path is a sensitive `/private/var/...`), a `docker` shim that records and fails, refusals asserted before docker. `gen_boundary_matrix.py` takes one file per suite; adding a suite is a constant, a file path, and one line in `parsed_names()`.
- The agent runs as the host uid (uid-agnostic image), so file permissions in a bind mount are not a boundary against it: `chmod a-w` stops accidents, not an agent.

## Goals / Non-Goals

**Goals:**
- Cut the write→execute path: no session may hold the running tjor tree writable without saying so explicitly.
- Keep "develop tjor inside a tjor session" working, via a one-command immutable install to launch from.
- Make provenance visible: which source an image was built from, and whether the running launcher is mutable.

**Non-Goals:**
- Auto-masking the checkout read-only inside the cage (rejected in #67; refusal + `self-install` keeps the developer use case).
- Image signing or attestation (ADR 0008 follow-up).
- Protecting an installed tree from the *host* user — `a-w` is a convenience; the host user owns the tree.

## Decisions

1. **Guard after the overlap check, before image resolution, on writable roots only.** The comparison set is `TJOR_WORKSPACE` + `TJOR_EXTRA_DIRS[@]`; containment is symmetric on component boundaries (`root == w`, `root == w/*`, `w == root/*`) — a writable parent covers the whole tree, and a writable subtree (`--dir <checkout>/images`) covers the entrypoint and proxy sources. Placement: after the cross-class overlap check, so every root is canonical and final, and before `resolve_agent_image`, so nothing is built or pulled for a launch that is then refused. *Alternative rejected:* folding the check into `dir_is_sensitive` — the override differs (`--allow-self-mount`, not `--unsafe-dir`), read-only is allowed here but not for sensitive paths, and the "sensitive" wording would mislead (the tree is not secret, it is *executable on the host*).
2. **No `.git` condition on the guard.** An installed tree (Homebrew `libexec`, or `~/.tjor/install/<sha>`) inside a writable mount is the same threat. The guard reads `TJOR_ROOT` and nothing else.
3. **`--allow-self-mount` is the override; read-only overlap is a notice.** A loud `warn` only when the override actually bypassed a refusal (the #64 pattern). `--dir-ro` naming the tree is legitimate (read the source from inside a session) and costs nothing, so it is announced, not refused. The override is also exported as `TJOR_ALLOW_SELF_MOUNT=1` for symmetry with `TJOR_UNSAFE_DIR`, though nothing in the cage consumes it (the cage cannot know where the host launcher lives).
4. **`self-install` archives the committed tree, atomically, and marks it.** `git -C TJOR_ROOT rev-parse --verify "<ref>^{commit}"` → sha; `git archive <sha> | tar -x -C <tmp>`; write `.tjor-source-sha`; `chmod -R a-w`; `mv <tmp> <install root>/<sha>` (atomic rename; a concurrent second install of the same sha loses cleanly); `ln -sfn <sha> current`. Archiving the commit, not the work tree, keeps the sha honest — the tree *is* that commit — and the command says uncommitted changes are excluded. The install root is `${TJOR_INSTALL_ROOT:-$HOME/.tjor/install}` (env override for tests and unusual layouts; no config key — the launcher must find it before any config is read, and an attacker-writable repo config must never redirect it). *Alternative rejected:* `cp -R` of the work tree — no sha to name it by, and it would silently ship uncommitted edits.
5. **The marker, not `.git`, is what "source tree" means.** `is_source_tree()` = `.git` dir or `.tjor-source-sha` file. `resolve_agent_image` pulls only when not a source tree. This is ADR 0008 decision 1 extended, recorded as an amendment there. *Alternative rejected:* keeping `.git` in the archive — `git archive` cannot, and a `.git` dir in an "immutable" tree invites `git pull` into it.
6. **`tjor.source-sha` on every local build.** `source_sha()`: marker content; else `git rev-parse HEAD` + `-dirty` if `git status --porcelain` is non-empty; else `release-<VERSION>`. Passed as `--label tjor.source-sha=…` to all three `docker build` calls. Cheap, and it makes "which code built this cage" answerable with `docker image inspect`.
7. **The install root joins `dir_is_sensitive`.** Third root in `init_sensitive_roots`, same symmetric containment. Threat: a session launched by launcher A mounts `~/.tjor/install` writable and rewrites the tree launcher B points at. This also means the self-installed tree, when it is the running one, is covered twice (guard + sensitive set); harmless.
8. **Doctor reports what it can verify, and drops the "configured profile" clause.** Root kind from `is_source_tree()` / marker; the checkout warning compares the would-be workspace (`git rev-parse --show-toplevel` from cwd, else cwd) against `TJOR_ROOT` with the guard's containment rule. The issue asks doctor to say "whether any configured profile mounts it writable" — tjor profiles (#29) declare no mounts, and there is no config for default `--dir`s, so there is nothing to inspect; doctor checks the launch-from-here case, which is the trigger #67 describes. Recorded here so the acceptance reads honestly.
9. **Coverage: a `self-mount` suite.** `tests/integration/self_mount_test.sh` sources `bin/tjor` with the real checkout as `TJOR_ROOT` (the guard's subject), a temp `HOME` under `~/.tjor/tmp`, and the docker shim. It drives `cmd_run` for the refusals (workspace = checkout; `--dir <checkout>/images`; `--dir <parent>`), the override, the read-only notice, and the disjoint case; `cmd_self_install` for the tree properties and idempotence; `resolve_agent_image` with a shimmed `cfg`-independent marker check; `build_agent` with the recording shim for the label; and `cmd_doctor` for the report. `gen_boundary_matrix.py` gains `SELF_MOUNT`; rendered rows: the three refusals and the install-root sensitivity.

## Risks / Trade-offs

- [Breaking for people who develop tjor inside tjor from the checkout's own `bin/tjor`] → deliberate (#67); the error names `tjor self-install`, `--dir-ro`, and `--allow-self-mount`; INSTALL.md gets the recipe; CHANGELOG marks it **BREAKING**.
- [`a-w` reads as a boundary] → the command output and docs say it is not; the guard and the install root's sensitivity are the controls.
- [`git archive` excludes files matched by `export-ignore`] → tjor has no `.gitattributes` export rules today; the test asserts `bin/tjor`, `compose.yaml`, `config/`, `python/`, `images/` are present in the installed tree.
- [A self-installed tree reads `VERSION` from the archived commit] → correct: it is that commit's version; a bare-tag pull is impossible from it anyway (source tree never pulls).
- [`docker build --label` changes image ids on every rebuild of a dirty checkout] → labels are metadata; a dirty checkout rebuilds anyway when sources change. The published pipeline is untouched.
- [Doctor's `report_tiers` needs docker] → unchanged; the new root-kind line prints before it.
- [A refused self-mount happens after the state dir exists and broker material is minted] → inherited from where the writable roots become final (after the extra-dir loops), exactly like a refused `--dir` today; the #64 workspace gate runs earlier only because it needs the workspace alone. Moving the workspace half of this guard into `resolve_session` is a small follow-up, not a blocker.

## Migration Plan

Additive commands and one refusal. Minor version bump (pre-1.0, breaking by design). Developers who launch from a checkout with that checkout (or a parent) mounted: run `tjor self-install`, point the launcher at `~/.tjor/install/current/bin/tjor`, re-run. Rollback: plain revert; installed trees under `~/.tjor/install` are inert files.

## Open Questions

None that change specs, approach, or tasks. Whether `self-install` should prune old shas (keep last N) is a follow-up nicety; #68 (state-dir inventory and prune) is the natural home.
