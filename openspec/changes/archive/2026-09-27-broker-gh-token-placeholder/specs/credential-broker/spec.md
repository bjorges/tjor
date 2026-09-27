# Spec Delta

## MODIFIED Requirements

### Requirement: Placeholder wiring is scoped to brokered destinations

The cage SHALL wire the placeholder GitHub git-credential helper only when the broker's configured destination hosts cover GitHub (`github.com` or `gist.github.com`), matched with the shared policy host matcher — never a second matcher implementation. When an enabled broker does not cover GitHub (e.g. a kube-only session), the session SHALL keep the same ambient GitHub auth path as a broker-less session (the `gh` fallback helper), so an intentional no-GitHub-credential posture behaves like one instead of presenting as broken git authentication.

The same rule SHALL govern the `gh` CLI: when the broker's destination hosts cover `api.github.com` on port 443 (shared matcher, port-aware), the cage SHALL export a fixed placeholder token as `GH_TOKEN` into the agent environment — never a real secret — so `gh` attempts auth with `Authorization: token <placeholder>` and the proxy substitutes the real credential toward the covered host. When the API host is not covered (a kube-only broker, a host list naming `github.com` without a glob, or no broker), `GH_TOKEN` SHALL be left unset and `gh` SHALL keep its ambient behavior. Because `gh` prefers `GH_TOKEN` over a stored `hosts.yml`, a token an agent minted in an earlier session SHALL NOT be used in a broker session that covers the API host; and because `gh auth login` refuses to run while `GH_TOKEN` is set, the easy in-cage path to minting a real token is removed in such sessions (the agent could still unset the variable — this narrows the ADR 0007 limitation, it does not close it, and documentation SHALL say so).

#### Scenario: Kube-only broker leaves GitHub auth ambient
- **WHEN** a session runs with `[broker] source = "kube"` (injection scoped to the cluster API host only)
- **THEN** the GitHub credential helper is the same `gh` fallback as in a broker-less session, and git never sends a placeholder credential to github.com

#### Scenario: GitHub-covering broker still gets the placeholder
- **WHEN** a session runs with a broker whose hosts cover github.com
- **THEN** the placeholder helper is wired (and the proxy substitutes the real credential), unchanged from before

#### Scenario: Coverage respects host globs
- **WHEN** the broker hosts contain a glob that matches github.com (e.g. via the shared matcher's semantics)
- **THEN** the placeholder helper is wired, identically to how the proxy scopes injection

#### Scenario: gh receives a placeholder when the API host is covered
- **WHEN** a session runs with a broker whose hosts cover `api.github.com` (e.g. the default `*.github.com`)
- **THEN** the agent environment contains `GH_TOKEN` set to the fixed placeholder, `gh` requests toward `api.github.com` carry the real credential upstream, and the real credential appears nowhere in the agent's environment, filesystem, or process memory

#### Scenario: gh gets nothing when the API host is not covered
- **WHEN** a session runs with a kube-only broker, a broker whose hosts name `github.com` without covering `api.github.com`, or no broker
- **THEN** `GH_TOKEN` is unset in the agent environment and `gh` behaves as in a broker-less session (the git helper wiring is decided independently, as before)

#### Scenario: A stored gh login is superseded in a broker session
- **WHEN** the session home already holds a `~/.config/gh/hosts.yml` with a token and the broker covers the API host
- **THEN** `gh` uses the `GH_TOKEN` placeholder and upstream only ever sees the brokered credential

#### Scenario: gh auth login is refused while the placeholder is set
- **WHEN** `gh auth login` is run inside a session where `GH_TOKEN` is the placeholder
- **THEN** `gh` refuses, stating that the `GH_TOKEN` environment variable is in use

#### Scenario: git is unaffected, and its scheme is honored
- **WHEN** `git fetch` or `git push` runs in a session where both the git helper and `GH_TOKEN` are wired
- **THEN** git authenticates through the placeholder helper, and the proxy re-issues the credential in git's Basic scheme (`x-access-token:<token>`), the only scheme GitHub's git endpoint accepts — while `gh`'s `token` scheme is kept for the API

#### Scenario: Substitution survives the resolve-and-pin
- **WHEN** the proxy has pinned the upstream address of a covered destination (so the request reports the pinned IP as its host) and the request carries the placeholder
- **THEN** the proxy still substitutes the real credential, judging the destination by the hostname the upstream certificate is verified against — and a request whose `Host` header names a covered destination inside a tunnel to a different server receives no credential

#### Scenario: Placeholder wiring survives the kernel-sandbox wrap
- **WHEN** the session runs under the kernel-sandbox tier
- **THEN** git inside the harness resolves the placeholder helper from the cage's system git config, and `gh` inside the harness holds the placeholder
