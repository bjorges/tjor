# tjor cage

You are running inside a tjor cage: an isolated container with a fail-closed
egress policy. This is infrastructure, not a restriction on your work — the
workspace is writable and you should work normally.

Practical notes:

- All network traffic goes through an egress proxy. A request denied by
  policy returns HTTP 403 with an `x-tjor-policy: deny` header — if a tool
  fails that way, the destination is not on the allowlist. Report it as a
  policy gap rather than retrying or trying to route around it.
- DNS resolves only allowlisted zones; other lookups return NXDOMAIN.
- Host credentials are not present in this environment by design. Never try
  to obtain or reconstruct credentials the environment does not provide.
- Your home directory persists across container restarts; the container
  itself is disposable.
- SSH egress does not exist here: git remotes for GitHub/GitLab are
  rewritten to HTTPS automatically. Anonymous pulls of public repos just
  work; for private repos or pushes, ask the user to run `gh auth login`
  followed by `gh auth setup-git` once in this session — never attempt to
  work around the missing SSH transport.
