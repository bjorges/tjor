# Contributing to tjor

tjor is a security boundary, so the way changes land is part of the product: every change is
reviewed as a diff, proven by CI, and recorded in the changelog before it reaches `main`.

## The flow

1. Branch from `main`. Never commit to `main` directly; the branch rules refuse it.
2. Make the change. Substantial capabilities go through OpenSpec (`openspec/`): propose → apply →
   archive, with the spec as the source of truth and an ADR under `docs/decisions/` for a
   project-level decision.
3. Run the local gates (bash ≥ 4.4, python3 ≥ 3.11, shellcheck; Docker only for the live tests):

   ```console
   $ python -m pytest python/tests -q          # unit, corpus, call-site parity, addon guards
   $ tests/doc_consistency.sh                   # README/matrix/dockerignore/compose invariants
   $ tests/slides_consistency.sh                # every spec capability has a reviewed slide
   $ shellcheck --severity=warning bin/tjor images/agent/entrypoint.sh proxy/entrypoint.sh tests/*.sh tests/integration/*.sh
   $ python3 python/gen_boundary_matrix.py      # when a probe was added, renamed or removed
   ```

4. Open a pull request. The template lists what a reviewer looks for. CI runs the unit job, the
   image contracts, the adversarial conformance suite and the live-session tests; all are
   required, so a merge waits for the slow ones (about 20 minutes).
5. Merge with **squash** (one logical change, the PR body as the commit message) or **rebase**
   when the commits are deliberately split. Merge commits are not used; history stays linear.

## Writing the change

- Pin, don't trust: actions by commit SHA, images by digest, downloads by SHA256
  (`docs/clean-room-charter.md`, L23). A mutable tag is not a pin.
- State limits plainly. A mechanism's residual goes in the README, the spec and the slide, in
  that order of importance.
- Cite the charter lesson or the issue a change answers (`(#72)`, `charter L26`).
- Provenance (ADR 0003): never name private reference systems, their owners or internal review
  events in commits, issues, specs or docs.
- A user-visible change gets a `CHANGELOG.md` entry under the next version's heading, and when a
  spec changed, its slide is re-read and re-pinned (`slides/agents.md`).

## Releasing

A release is a pull request like any other: bump `VERSION`, give the version its `CHANGELOG.md`
section (`## [X.Y.Z] — YYYY-MM-DD — title`), merge. Then tag the **merge commit on `main`**
(squashing changes the SHA, so never tag the branch commit):

```console
$ git switch main && git pull
$ git tag vX.Y.Z && git push origin vX.Y.Z
```

The tag triggers `publish-images.yml`: multi-arch agent and proxy images to GHCR and the GitHub
Release with that CHANGELOG section as its notes. Tagging is the only manual release step.

## Dependencies

Renovate opens one grouped pull request per week for non-major updates (actions digests, images,
the slides' npm packages). Review it like any other change: a digest bump pulls new upstream code
into CI. Major updates arrive as their own PRs.
