# Contributing to tjor

tjor is a security boundary, so the way changes land is part of the product: every change is
reviewed as a diff, proven by CI, and recorded in the changelog before it reaches `main`.

## The flow

1. Branch from `main`. Never commit to `main` directly: it is the merge target, and the pull
   request's CI is the gate.
2. Make the change. Substantial capabilities go through OpenSpec (`openspec/`): propose → apply →
   archive, with the spec as the source of truth and an ADR under `docs/decisions/` for a
   project-level decision.
3. Run the local gates (bash ≥ 4.4, python3 ≥ 3.11, shellcheck; Docker only for the live tests):

   ```console
   $ python -m pytest python/tests -q          # every python suite: policy, broker, kube, gateway, git-check, parity, addon guards, ...
   $ tests/doc_consistency.sh                   # README/matrix/dockerignore/compose invariants
   $ tests/slides_consistency.sh                # every spec capability has a reviewed slide
   $ shellcheck --severity=warning bin/tjor images/agent/entrypoint.sh proxy/entrypoint.sh tests/*.sh tests/integration/*.sh
   $ python3 python/gen_boundary_matrix.py      # when a probe was added, renamed or removed
   ```

4. Open a pull request. The template lists what a reviewer looks for. CI runs the unit job, the
   image contracts, the adversarial conformance suite and the live-session tests in parallel; a
   full run takes a few minutes. A merge waits for every one of them to be green.
5. Merge with **squash** (one logical change; write the PR title and body as the commit message
   they become) or **rebase** when the commits are deliberately split. Merge commits are not used,
   so history stays linear.

## Writing the change

- Pin, don't trust: actions by commit SHA, images by digest, downloads by SHA256
  (`docs/clean-room-charter.md`, L23). A mutable tag is not a pin.
- State limits plainly. A mechanism's residual goes in the README, the spec and the slide, in
  that order of importance.
- Cite the charter lesson or the issue a change answers (`(#72)`, `charter L26`).
- Provenance (ADR 0003): never name private reference systems, their owners or internal review
  events in commits, issues, specs or docs.
- A user-visible change gets a `CHANGELOG.md` entry under `## [Unreleased]`; the release PR turns
  that heading into the version's. When a spec changed, its slide is re-read and re-pinned
  (`slides/agents.md`).

## Repository settings

The flow above is enforced by repository settings, not by files, so this is the record of what a
maintainer enables (and what a reader should expect): a ruleset on `main` that blocks direct pushes
and requires every `ci.yml` job before a merge (not `slides.yml`, which deploys after it); squash
and rebase merges only, the squash message taken from the pull request body; branches deleted on
merge; private vulnerability reporting enabled so the `SECURITY.md` link works. The required-check
list cannot drift from `ci.yml`: `tests/ruleset_consistency.sh`, run by the unit job, compares the
run's jobs with the ruleset's required checks in both directions (a new job must be added to the
ruleset by name before its pull request can merge).

## Releasing

A release is a pull request like any other: bump `VERSION`, turn `## [Unreleased]` into the
version's `CHANGELOG.md` heading (`## [X.Y.Z] — YYYY-MM-DD — title`) and leave a fresh, empty
`## [Unreleased]` above it (`tests/doc_consistency.sh` checks both, and that the heading names
`VERSION`), merge. Then tag the **merge commit on `main`** (squashing changes the SHA, so never
tag the branch commit):

```console
$ git switch main && git pull
$ git tag vX.Y.Z && git push origin vX.Y.Z
```

The tag triggers `publish-images.yml`: multi-arch agent and proxy images to GHCR and the GitHub
Release with that CHANGELOG section as its notes. The Homebrew tap
([bjorges/homebrew-tap](https://github.com/bjorges/homebrew-tap)) follows on its own: its
workflow polls every six hours, and when it sees the new release it rewrites the formula's url and
checksum, installs and tests it with Homebrew, and commits the bump (a failed check leaves the tap
on the previous version and that run red). To serve the new version at once rather than within six
hours, run it by hand right after tagging:

```console
$ gh workflow run update-tjor.yml -R bjorges/homebrew-tap
```

Tagging is the only manual release step.

## Dependencies

Renovate opens one grouped pull request per week for non-major updates (actions digests, images,
the slides' npm packages). Review it like any other change: a digest bump pulls new upstream code
into CI. Major updates arrive as their own PRs.
