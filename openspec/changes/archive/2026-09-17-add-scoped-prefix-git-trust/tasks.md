# Tasks — scoped prefix git trust for mounted trees

## 1. Implementation

- [x] 1.1 `images/agent/entrypoint.sh` step 3: for each `TJOR_SAFE_DIRS`
      line NOT listed in `TJOR_RO_DIRS`, register `safe.directory <root>`
      AND `safe.directory <root>/*`; RO roots keep the exact entry only.
      Normalize trailing slashes; FATAL (boundary exit code) on a
      degenerate root (empty, `/`, literal `*`, ends in `/*`) — never
      register it. Verify: entries visible via
      `git config --system --get-all safe.directory` in a container
      (starred for rw, exact-only for ro); shellcheck clean at warning
      severity, zero new findings.
- [x] 1.2 `images/agent/Dockerfile`: assert `git --version` ≥ 2.46
      immediately after the apt install; the build fails otherwise
      (comment: git is the base distro's apt package, NOT sha256-pinned —
      this floor is the gate that keeps `/*` semantics from silently going
      inert). Verify: image builds today; a forced-failure dry run of the
      version comparison logic is exercised in the build script check.
- [x] 1.3 `bin/tjor`: refuse at root resolution any workspace/`--dir`/
      `--dir-ro` path that resolves to a degenerate form (empty, `/`,
      literal `*`, basename `*`, ends in `/*` after trailing-slash
      normalization) with a clear error; update the
      `TJOR_SAFE_DIRS`/`TJOR_RO_DIRS` contract comment — the writability
      class gates starred trust registration (decision 2). Verify:
      launcher refusal exercised in multirepo_test.sh; comment matches the
      shipped mechanism; shellcheck clean.

## 2. Tests (multirepo_test.sh — all trust assertions under GIT_TEST_ASSUME_DIFFERENT_OWNER=1)

- [x] 2.1 Vacuity guard baseline: with `GIT_TEST_ASSUME_DIFFERENT_OWNER=1`,
      an agent-owned repo in an UNREGISTERED location is refused — proving
      the ownership short-circuit is disabled and the suite's trust
      assertions are real. Verify: check present and passing.
- [x] 2.2 The #53 headline flow: in-cage
      `git worktree add <mounted-parent>/.worktrees/wt1` from a repo under
      a `--dir`'d parent, then `git status`/`log` in the new worktree
      succeeds under `GIT_TEST_ASSUME_DIFFERENT_OWNER=1`. Verify: test
      passes on the live engine.
- [x] 2.3 A `--dir`'d parent with two pre-existing nested repos — git works
      in both (var set). A nested pre-existing repo under the `--dir-ro`
      mount is REFUSED (var set) — the read-only protection scenario.
      Verify: both pass.
- [x] 2.4 Negative suite (var set): out-of-root repo refused; sibling
      `<root>-evil/repo` refused (prefix boundary); symlink under a
      writable root pointing at an out-of-root repo — git against the
      resolved target refused. Verify: all three pass.
- [x] 2.5 Guard tests: launching with a `--dir` whose basename is `*`
      (create the literal dir) aborts with the degenerate-root error;
      synthetic entrypoint check — a `TJOR_SAFE_DIRS` list containing `/`
      or a trailing-`/*` entry makes the entrypoint exit with the boundary
      code and register nothing; a trailing-slash root registers
      normalized (no `root//*`). Extend the existing colon-path check to
      assert the starred sibling `/repos/has:colon/inner/*` is intact.
      Verify: all pass.

## 3. Docs

- [x] 3.1 `docs/decisions/0008-prebuilt-image-trust.md` §4: amend "exact
      paths" to "the exact writable trees, read-only paths exactly",
      appending the git ≥ 2.46 prefix-trust reasoning, the cardinality
      framing, and the writable-only scoping (append, don't rewrite
      history). Verify: matches design decisions 2–3.
- [x] 3.2 README: multi-repo section — writable mounted trees are
      git-trusted as trees (worktrees/clones created mid-session just
      work); read-only mounts keep exact trust and why, with the two
      workarounds; hardened-profile note records the mask_dirs answer
      (fresh worktrees re-materialize unmasked content → pair mask_dirs
      with the managed tier; RO profiles additionally keep the ownership
      barrier). Verify: tests/doc_consistency.sh passes.
- [x] 3.3 CHANGELOG `[Unreleased]`: entry naming #53, the mechanism, the
      writable-only scoping and why, the guards, and the build-time git
      floor. Verify: claims match shipped behavior exactly.

## 4. Verification sweep

- [x] 4.1 Full sweep: python suite, shellcheck (warning severity, zero new
      findings), doc-consistency, and multirepo + landlock + profile
      integration tests green on the live engine (image rebuilt so the
      entrypoint and Dockerfile changes are in the image under test).
      Verify: all pass locally.
