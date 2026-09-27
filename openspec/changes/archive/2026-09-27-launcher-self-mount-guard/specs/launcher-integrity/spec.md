# Spec Delta

## Purpose

Protects the launcher's own code tree from the sessions it launches: the tree that runs unsandboxed on the host (and builds the cage's images) is never mounted writable into a cage, an immutable source install is one command away, built images say which source they came from, and `tjor doctor` tells the operator whether the running tree is mutable.

## ADDED Requirements

### Requirement: The running tjor tree is never mounted writable

At launch, after every mount root has been canonicalized and the mount set is final, the launcher SHALL compare its own installation root (physical path) against each **writable** root — the primary workspace and every `--dir` path. When the installation root equals a writable root, lies under one, or contains one (judged on path-component boundaries), the launch SHALL abort with an error naming both paths and the remedies (run tjor from a separate install, mount the tree read-only, or pass the override), before any image is resolved or built and before any container exists. This applies to every installation kind — a git checkout and an installed tree alike.

`--allow-self-mount` SHALL be the single explicit override; when it actually overrides a refusal the launcher SHALL print a loud warning naming the tree. A **read-only** overlap (`--dir-ro` naming the tree, a parent of it, or a directory under it) SHALL be allowed and announced with a one-line notice.

#### Scenario: Checkout as the workspace is refused

- **WHEN** `tjor run` is invoked from the git checkout that `bin/tjor` runs from, so the workspace equals the installation root
- **THEN** the launch aborts naming the installation root and the workspace, and no image is resolved or built

#### Scenario: A parent of the checkout mounted writable is refused

- **WHEN** `tjor run --dir <parent of the checkout>` is invoked from an ordinary repository
- **THEN** the launch aborts naming the installation root and the `--dir` path

#### Scenario: A directory inside the checkout mounted writable is refused

- **WHEN** `tjor run --dir <checkout>/images` is invoked from an ordinary repository
- **THEN** the launch aborts naming the installation root and the `--dir` path

#### Scenario: Override launches loudly

- **WHEN** `tjor run --allow-self-mount` is invoked with a mount set the guard would otherwise refuse
- **THEN** the launch proceeds and a warning names the tree now exposed writable

#### Scenario: Read-only self-mount is allowed with a notice

- **WHEN** `tjor run --dir-ro <checkout>` is invoked from an ordinary repository
- **THEN** the launch proceeds, printing a one-line notice that the running tjor tree is mounted read-only

#### Scenario: Disjoint roots are unaffected

- **WHEN** `tjor run` is invoked from an ordinary repository that neither contains nor lies under the installation root, with no `--dir` touching it
- **THEN** the launch proceeds with no self-mount output

### Requirement: Self-install produces an immutable source tree

`tjor self-install [--ref <commit-ish>]` SHALL, when run from a git checkout, export the **committed** tree of the given ref (default `HEAD`) into `<install root>/<sha>/`, where the install root defaults to `~/.tjor/install`; write a `.tjor-source-sha` marker file holding the full commit sha; remove write permission from every file and directory in the tree; and point a `<install root>/current` symlink at that sha. It SHALL print the path launchers should run (`<install root>/current/bin/tjor`) and, when a previous `current` existed for a different sha, the one-line git log between the two. Installing a sha that is already installed SHALL be idempotent (the tree is left as is; `current` is repointed). Uncommitted changes in the checkout SHALL NOT be included, and the command SHALL say so. Run from a tree that is not a git checkout, the command SHALL fail with a clear error.

The install root SHALL be part of the sensitive set (`session-launch`): a session launched by any tjor must not be able to mount it writable without the explicit sensitive-path override.

#### Scenario: Install from HEAD

- **WHEN** `tjor self-install` is run in a git checkout
- **THEN** `<install root>/<HEAD sha>/` exists, contains `bin/tjor`, `VERSION` and `.tjor-source-sha` equal to the sha, no file or directory under it is writable, and `<install root>/current` resolves to it

#### Scenario: Launching from the installed tree works with the same mounts

- **WHEN** `<install root>/current/bin/tjor run` is invoked from the original checkout as the workspace
- **THEN** the self-mount guard does not fire (the installation root and the workspace are disjoint) and the launch proceeds

#### Scenario: Re-installing the same sha

- **WHEN** `tjor self-install` is run twice for the same commit
- **THEN** the second run leaves the tree unchanged, repoints `current`, and reports the sha as already installed

#### Scenario: Not a checkout

- **WHEN** `tjor self-install` is run from an installed tree (no `.git`)
- **THEN** the command fails with an error stating that self-install needs a git checkout

### Requirement: A self-installed tree builds locally

The launcher SHALL treat a tree carrying the `.tjor-source-sha` marker exactly as it treats a git checkout for image resolution: it SHALL always build the agent, proxy and conformance images locally from that tree and SHALL NOT pull a published image, regardless of `[images] publish`.

#### Scenario: Marker present

- **WHEN** `tjor run` is invoked from a self-installed tree with `[images] publish` at its default
- **THEN** the launcher builds locally and never attempts a registry pull

### Requirement: Built images record their source

Every image the launcher builds locally (agent, proxy, conformance) SHALL carry the label `tjor.source-sha`: the marker's sha for a self-installed tree; the checkout's `HEAD` sha, suffixed `-dirty` when the work tree has uncommitted changes, for a git checkout; `release-<VERSION>` for any other installation.

#### Scenario: Build from an installed tree

- **WHEN** an agent image is built from a self-installed tree
- **THEN** the build carries `--label tjor.source-sha=<the marker's sha>`

#### Scenario: Build from a dirty checkout

- **WHEN** an agent image is built from a git checkout with uncommitted changes
- **THEN** the label value is the `HEAD` sha with a `-dirty` suffix

### Requirement: Doctor reports launcher mutability

`tjor doctor` SHALL state which kind of tree is running — a mutable git checkout, a self-installed tree (with its sha) that is read-only, or an installed release — on its root line. For a git checkout it SHALL additionally warn when launching from the current directory would mount that checkout writable (the would-be workspace equals, contains, or lies under the installation root), naming `tjor self-install` as the remedy. Outside any repository the report SHALL still succeed.

#### Scenario: Doctor inside the checkout

- **WHEN** `tjor doctor` is run from within the git checkout that `bin/tjor` runs from
- **THEN** the root line says the tree is a mutable git checkout and a warning says a launch from here would mount it writable

#### Scenario: Doctor from an installed tree

- **WHEN** `<install root>/current/bin/tjor doctor` is run
- **THEN** the root line names the self-installed sha and says the tree is read-only, with no self-mount warning
