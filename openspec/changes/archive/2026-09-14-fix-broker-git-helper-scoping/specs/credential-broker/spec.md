## ADDED Requirements

### Requirement: Placeholder wiring is scoped to brokered destinations

The cage SHALL wire the placeholder GitHub git-credential helper only when the broker's configured destination hosts cover GitHub (`github.com` or `gist.github.com`), matched with the shared policy host matcher — never a second matcher implementation. When an enabled broker does not cover GitHub (e.g. a kube-only session), the session SHALL keep the same ambient GitHub auth path as a broker-less session (the `gh` fallback helper), so an intentional no-GitHub-credential posture behaves like one instead of presenting as broken git authentication.

#### Scenario: Kube-only broker leaves GitHub auth ambient
- **WHEN** a session runs with `[broker] source = "kube"` (injection scoped to the cluster API host only)
- **THEN** the GitHub credential helper is the same `gh` fallback as in a broker-less session, and git never sends a placeholder credential to github.com

#### Scenario: GitHub-covering broker still gets the placeholder
- **WHEN** a session runs with a broker whose hosts cover github.com
- **THEN** the placeholder helper is wired (and the proxy substitutes the real credential), unchanged from before

#### Scenario: Coverage respects host globs
- **WHEN** the broker hosts contain a glob that matches github.com (e.g. via the shared matcher's semantics)
- **THEN** the placeholder helper is wired, identically to how the proxy scopes injection
