# Design: add-repo-config-and-policy-ergonomics

*(Added retroactively — this change shipped without a design.md; recorded here
because its trust/hash-pinning surface warrants an explicit rationale.)*

> **Provenance note.** Three items below were NOT part of the original v0.6.0
> design: the terminal-escape sanitizer, the two-step `tjor trust` confirm gate,
> and the `resolve_session`/`session_setup` split were **vulnerabilities found by
> a later external review and fixed in v0.9.1** (terminal-escape injection in the
> trust review; read-only commands minting credentials). They are documented here
> as part of the capability's current design, but they were corrections, not
> foresight — recorded honestly, as with `add-multi-repo`'s design.md.

## Context

Two frictions after prebuilt images made first run fast: an egress denial is
opaque (what was blocked? how do I allow it?), and config is global while
different repos need different allowlists. The second is security-sensitive: a
repo config can *widen* the boundary (allowlist a host, set a broker), so a
committed `.tjor/` must never be honored just because it exists — a malicious
contributor, or a compromised agent writing to the workspace, could otherwise
grant itself egress.

## Goals / Non-Goals

**Goals:** a repo may carry `.tjor/{policy,config}.toml`, honored only after
explicit operator approval pinned to exact content; legible denials with a
one-command widen loop.

**Non-Goals:** per-repo broker *secrets*; an observe/learn mode that logs
would-be denials without blocking (a loud, non-default follow-up).

## Decisions

- **Trust is content-hash-pinned, not path-pinned.** Approval records the
  SHA-256 of the exact file (`~/.config/tjor/trusted.toml`); `is_trusted` is a
  byte-exact comparison, so *any* later edit — whitespace included — revokes
  trust until re-approved. This makes "approve once, then the file changes
  under you" impossible. The store is never mounted into the agent, and
  `_load_store` fails closed on a corrupt/unreadable store. *Alternative
  rejected:* trusting a path or a signature — a path can be edited after
  approval; signatures are heavier than this single-user local tool needs.
- **Approval is a genuine two-step act.** `tjor trust` shows the content, then
  requires a separate confirmation (interactive `[y/N]`, or `--yes` for
  reviewed automation); `--show` reviews without approving. Display and
  approval must not be the same keystroke, or "review before trust" is not a
  gate.
- **Untrusted content is sanitized before it reaches the terminal.** The file
  under review is attacker-influenced, so it is rendered through a
  terminal-escape sanitizer (`tjor_safeprint`) that neutralizes ANSI/OSC
  escapes and Unicode bidi/format controls — otherwise a hostile file could
  visually hide or reorder what the operator approves, defeating the hash gate
  (the hash would pin exactly the misrepresented bytes). The same sanitizer
  guards every other place tjor prints attacker-influenced content (the
  session denial log). *This is a distinct threat class — "what untrusted
  bytes do to the terminal displaying them" — not covered by the boundary
  model itself.*
- **`policy add` widening a trusted repo policy is confirmed, not silent.**
  Adding a host to a trusted `.tjor/policy.toml` re-approves it (its hash
  changes); that re-blessing is made explicit and confirmed, so an agent's
  suggested `tjor policy add …` cannot quietly re-widen a repo file. Adding to
  the user policy (no re-approval) stays a single quick command.
- **The allowlist edit is semantically verified, not just parse-checked.**
  `tjor policy add` re-parses the result and asserts the host is actually in
  the effective `hosts.allow`; a regex insert that lands inside a preceding
  multi-line string (valid TOML, wrong table) fails loudly instead of a silent
  no-op.
- **Denials are observable per session.** The proxy appends each denied egress
  (sanitized host, rule, time; bounded in count) to a session-scoped log;
  `tjor denials` reads it. Resolving that path is a read-only operation and
  must not assemble broker material (which, for a kube source, would mint a
  live credential) — so the read-only/teardown commands resolve the session
  without the broker step.

## Risks / Trade-offs

- **A trusted repo config is still operator-granted power.** Approval means the
  operator vouched for that content; tjor guarantees only that what they
  approved is exactly what runs, and that any change re-prompts. The sanitizer
  ensures "what they approved" equals "what they saw".
- **Content-hash pinning is deliberately brittle** (a formatting change revokes
  trust). That is the safe direction: re-approval is cheap, silent drift is
  not.

## Verification

Unit tests: trust store round-trip + revoke-on-edit, 0600 store perms, repo
config layering (trusted vs ignored), policy-edit host-add including the
multi-line-string semantic-noop refusal, and the terminal-escape sanitizer
(ANSI/OSC/bidi neutralized, legit text preserved). Integration
(`ergonomics_test.sh`): init → untrusted-ignored → confirm-refused-without-tty
→ trusted-honored → edit-revokes → escape-review-neutralized → policy add →
denial log surfaced.
