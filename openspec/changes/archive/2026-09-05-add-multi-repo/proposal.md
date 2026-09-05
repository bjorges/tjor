# Proposal: add-multi-repo

## Why

One caged session should be able to work across several repositories at once — the original brief required "multiple git repos simultaneously, like the `~/scratch` setup," and today `tjor run` mounts exactly one git toplevel. Cross-repo work (a service + its client, a repo + a shared library) is common and currently forces separate sessions with no shared context.

## What Changes

- `tjor run --dir <path>` (repeatable) mounts additional directories into the session, each at its **same absolute host path** (same-path fidelity, charter L15), writable by the agent.
- Each extra dir is resolved to an absolute path, verified to exist and to be shared with the container runtime (the VM-share check that already guards the primary workspace), and refused loudly otherwise.
- The **primary** workspace (the invocation's git toplevel, as today) still anchors the session: session id, identity, and the harness's cwd are unchanged. Extra dirs are additional mounts, not additional session identities — so adding `--dir` to the same repo/`--session` is the same session.
- Extra mounts are delivered via `compose run --volume` (no compose-file change, no per-session override).

Out of scope: per-repo identity headers (the primary repo remains `x-agent-repo`), auto-discovery of related repos, and cross-repo credential scoping (the broker's host-scope is unaffected).

## Capabilities

### Modified Capabilities

- `session-launch`: the launcher accepts repeatable `--dir` and mounts each at its host path, verified.

## Impact

- Code: launcher (`--dir` parsing, per-dir verification, `-v` args on the agent run), usage/README, an integration test launching one session over two repos and asserting both are mounted at their host paths and writable with working git.
- No breaking changes: a session with no `--dir` behaves exactly as today.
