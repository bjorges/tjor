# Proposal: add-repo-config-and-policy-ergonomics

## Why

Now that first run is fast (prebuilt images), the next wall a user hits is an egress **denial** with no obvious way to see what was blocked or add it — the single most likely first-hour frustration. And different repos need different allowlists, but config is global today. This change makes denials legible and the allowlist easy to grow (#23), and lets a repo carry its own config — trust-gated, because a repo config can widen the boundary (#22).

## What Changes

**Per-repo config (#22).**
- A repo may carry `.tjor/policy.toml` and `.tjor/config.toml`. They are honored **only after the user approves them** with `tjor trust`, pinned by content hash in a user trust store — because a committed config could allowlist a malicious host or set a broker. An unapproved repo config is **ignored with a loud warning**, never silently honored.
- Precedence when trusted: built-in defaults → user config → repo `.tjor/config.toml` → `--config <path>`. Policy analogously (repo `.tjor/policy.toml` before the packaged default, after the user's).
- `tjor init` scaffolds a starter `.tjor/` (policy + config) in the current repo.
- `tjor trust [--show]` prints the repo config/policy and records approval (its content hash); a later change to the file requires re-approval.

**Policy ergonomics (#23).**
- `tjor policy <url> --explain` shows which stage/rule decided and the matching pattern (the engine already computes this).
- `tjor policy add <host>` appends a host to the active policy's allow list (user or repo, whichever is in effect), so widening is one command.
- A **session denial log**: the proxy records each denied egress (host, rule, time) to a file in the session state; `tjor denials [session]` reads it — closing the "what got blocked → add it" loop.

Out of scope: an "observe/learn" mode that logs would-be denials without blocking (a follow-up; it must be loud and non-default), and per-repo broker secrets.

## Capabilities

### New Capabilities

- `repo-config-trust`: repo-local config/policy honored only after content-pinned approval.
- `policy-ergonomics`: `--explain`, `policy add`, and a session denial log with `tjor denials`.

### Modified Capabilities

- `session-launch`: config/policy resolution gains the trust-gated repo layer.

## Impact

- Code: launcher (`init`, `trust`, `denials`, `policy add`, `--explain`, repo-config resolution + trust store), config module (repo layer), proxy addon (append denials to a mounted log), tests (trust gating, explain, add, denial log), and a README pass (quickstart, config layering, the deny→add loop, troubleshooting).
- No breaking changes: no `.tjor/` and no trust store means today's behavior exactly.
