# Design — scoped prefix git trust for mounted trees

*Revised 2026-09-16 after a four-lens external review (deep-reasoning
architecture, adversarial security, two independent cross-model critiques).
The mechanism was endorsed by all four reviewers; the revisions below adopt
their convergent findings: writable-only scoping, wildcard-degeneration
guards, non-vacuous tests, and a real git version floor.*

## Context

See proposal.md for motivation. Load-bearing facts:

- The entrypoint (step 3) registers `safe.directory` in **system** git
  config, once per container start: unset-all, then one exact entry per
  `TJOR_SAFE_DIRS` line (newline-delimited; colon-safe). git's
  `safe.directory` matching is exact-string; no prefix/ancestor semantics
  for plain entries; ADR 0008 §4 deliberately forbids `*`.
- Ground truth verified in the shipped image (`tjor-agent-opencode:local`,
  git 2.47.3), 2026-09-15/16:
  - git ≥ 2.46 supports trailing-`/*` entries: with system
    `safe.directory = /x/parent/*`, a direct child repo AND an arbitrarily
    nested repo (`/x/parent/a/b/repo2`) owned by a **different uid** are
    both trusted; `/x/other/repo3` outside the starred root is refused;
    the sibling `/x/own-evil/r` is NOT matched by `/x/own/*`.
  - **Ownership short-circuit**: a repo owned by the executing uid is
    trusted with no `safe.directory` at all — on uid-aligned engines a
    naive test passes whether or not the fix exists. `safe.directory` is
    only consulted for foreign-owned repos.
  - **`GIT_TEST_ASSUME_DIFFERENT_OWNER=1`** is honored by the shipped git:
    it forces the ownership check even for own-uid repos, making trust
    assertions real.
  - **`safe.directory = /*` trusts every absolute path at any depth** —
    functionally identical to the bare `*` ADR 0008 forbids. Degenerate
    roots (empty, `/`, literal `*`, trailing `/*`) must never reach
    registration.
  - **git is NOT sha256-pinned**: it enters the image via
    `apt-get install git` from the (digest-pinned) base distro. The ≥ 2.46
    property currently holds by the distro's shipped version, not by any
    gate.
- Dubious-ownership refusal is itself a security control: git refuses to
  honor *any* configuration in an untrusted repo, which is what stops a
  hostile pre-existing nested `.git/config` — `core.fsmonitor`,
  `core.pager`, `filter.*.clean/smudge`, hooks, and repo-local
  `credential.helper` entries that can interfere with the cage's
  broker-placeholder helper wiring — from executing during plain
  `git status`/`git log` in unvetted content.

## Goals / Non-Goals

**Goals:**

- "Create a worktree, then work in it" works on the first try, in every
  session, with no agent-visible extra step.
- Trust stays scoped to operator-approved roots; never a bare `*`, never a
  degenerate entry equivalent to one.
- Read-only mounts keep their protection against pre-existing hostile git
  config.
- Tests that fail when the mechanism is broken, missing, or unsupported.

**Non-Goals:**

- Tree trust for read-only roots (decision 2 — deliberately excluded, not
  deferred).
- Trusting anything outside the approved mount roots.
- Sanitizing or containing nested repos' `.git/config` content under
  writable roots — the widening there is documented and scoped, not
  eliminated.

## Decisions

1. **Use upstream prefix trust; register `<root>` and `<root>/*` per
   WRITABLE approved root.** The entrypoint's existing loop adds the
   starred sibling for each `TJOR_SAFE_DIRS` entry NOT listed in
   `TJOR_RO_DIRS`. The bare entry keeps the root itself trusted; `/*`
   covers descendants. *Alternatives rejected (the issue's own candidates,
   pre-dating the git ≥ 2.46 check):* a mediated root-privileged trust
   helper (new privileged in-cage surface; registrations vanish on
   restart), a transparent git wrapper (drift; misses non-git tools), a
   filesystem watcher (races; same restart problem). All four external
   reviewers endorsed this mechanism choice.

2. **Read-only roots keep exact-match registration — the writability class
   is load-bearing for trust eligibility.** Three of four reviewers
   independently converged on the same gap in the first draft: extending
   tree trust to `--dir-ro` parents would *remove* the ownership-refusal
   protection exactly where unvetted pre-existing content is expected (the
   read-only investigation profile), because `:ro` blocks writes, not
   config execution. And tree trust is never *needed* there: nothing new
   can come into existence under a `:ro` mount, so the mid-session-creation
   case only ever occurs under writable roots. Consequences:
   - `TJOR_RO_DIRS` regains an eligibility role (the previous change's
     contract comment in `bin/tjor` is updated to say the writability
     class gates starred registration — not dropped as first drafted).
   - The trade-off is stated, not hidden: git reads in nested repos under a
     `--dir-ro` parent stay refused. Workarounds documented: mount the
     individual repos `--dir-ro` (each gets exact trust), or mount the
     parent writable and accept decision 3's widening.

3. **The widening under writable roots is bigger in kind, and the scoping
   is the answer — not a "same class" claim.** `<root>/*` trusts every
   repository that exists or will ever exist under the root, including
   nested/vendored repos the operator never individually reviewed — a
   cardinality the first draft's "same residual class" framing understated.
   The design's answer is the writable-only scope: under a writable root
   the operator has already accepted agent-driven mutation of the entire
   tree — agent-created repos are own-uid (trusted by git regardless), and
   the cage (non-root, no direct egress) bounds what any trusted config can
   do. No opt-out knob: the meaningful boundary is writability, which is
   already an explicit per-mount operator choice (`--dir` vs `--dir-ro`).
   ADR 0008 §4 is amended from "exact paths" to "the exact writable trees,
   read-only paths exactly", with this reasoning appended (the ADR records
   history; append, don't rewrite).

4. **Degenerate roots are refused on both sides.** Verified: `/*` is
   blanket trust. So the launcher (at root resolution) dies on an approved
   root that is empty, `/`, literally `*`, or ends in `/*` (covers a
   directory literally named `*`, whether real or a symlink), and
   normalizes trailing slashes (a `root/` would register an inert
   `root//*`); the entrypoint independently re-validates before
   registering and exits with the boundary code for non-launcher starts.
   Fail closed, loudly — a skipped-but-silent entry would leave a session
   looking covered while not being it.

5. **The git ≥ 2.46 floor becomes a build gate, not an assumption.** The
   first draft claimed git was "image-pinned and sha256-gated" — false;
   it is the base distro's apt package. The Dockerfile now asserts
   `git --version` ≥ 2.46 immediately after the apt install and fails the
   build otherwise, so a base-image bump to an older distro can never
   silently ship inert `/*` entries. The integration tests remain the
   behavioral backstop.

6. **mask_dirs interaction — the decision handed off by the #43 change,
   answered.** Making worktree creation routine means fresh worktrees
   re-materialize working-tree content that launch-time `mask_dirs`
   masking does not cover (its documented mid-session residual, now
   exercised more often). The answer: the managed opencode tier (#46) is
   the control that survives mid-session tree growth, and hardened
   profiles pair `mask_dirs` with a managed config precisely for this;
   additionally, with tree trust scoped to writable roots, a read-only
   investigation profile keeps the ownership-refusal barrier on top. The
   option of the trust layer consulting `mask_dirs` remains open but is
   not needed: it would gate git trust on a masking config whose residual
   is already covered by the managed tier, adding coupling without closing
   a vector the cage doesn't already bound. Recorded in README's
   hardened-profile guidance.

## Risks / Trade-offs

- [A future base image ships git < 2.46] → the Dockerfile floor assertion
  fails the build (decision 5); the multirepo worktree-flow test fails
  loudly on any image that slips through.
- [Vendored-repo widening under writable roots surprises a reviewer] →
  stated in the spec requirement text, ADR 0008 §4, and the README, with
  the cardinality framing from decision 3 — not a "same class" gloss.
- [Investigation profiles lose nested-repo git reads under `--dir-ro`
  parents] → deliberate (decision 2); documented workarounds; the profile
  guide states the trade-off.
- [An operator mounts a parent so broad it approximates `*` (e.g.
  `--dir $HOME`)] → already refused by the sensitive-path gate unless
  `--unsafe-dir` explicitly accepts the exposure; degenerate forms that
  would literally become `*` are refused unconditionally (decision 4).
- [Symlink under a writable root pointing outside] → git resolves the
  repository's real path before the safe.directory comparison, so the
  out-of-root target stays refused; asserted by a dedicated test rather
  than by analysis alone.

## Migration Plan

Purely additive entries in system git config, derived at each container
start; no stored state changes. Rollback = revert the commit (the next
container start re-derives the old exact-only entries). No user action.
