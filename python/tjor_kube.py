#!/usr/bin/env python3
"""Pure helpers for the `kube` credential-broker source (#26).

The launcher mints a short-TTL Kubernetes ServiceAccount token host-side with
`kubectl create token` and hands it to the proxy as a `pat`-shaped credential,
injected as the bearer token toward the cluster API server host ONLY. The
agent holds only a placeholder; the real token never enters the cage.

These are the PURE transforms that path needs, kept here (not inline in the
launcher/entrypoint) so they are unit-tested against the real code that runs:

  * `api_host(server)` — the host of a kubeconfig cluster server URL: the
    egress-allowlist target the operator must `tjor policy add`, and the
    proxy's scoped SSRF-guard exemption (#45). Hostname-level questions only.
  * `api_origin(server)` — the exact `host:port` origin (#49): the broker's
    injection scope, so the SA token never reaches a same-hostname service on
    a different port. Explicit port, else the scheme default (443/80).
  * `same_server(a, b)` — whether two server values name the same API server
    (#58): canonical (scheme, host, effective-port) equality, so an explicit
    `kube_api_host` pin is validated against the active context's server
    without false mismatches over spelling.
  * `kubeconfig(server, ca_path, token)` — a minimal in-cage kubeconfig that
    points at the REAL API server but carries only a PLACEHOLDER bearer token;
    `kubectl` sends `Authorization: Bearer <placeholder>` and the proxy
    overwrites it with the real SA token. Emitted as JSON (a valid kubeconfig —
    client-go's YAML loader accepts JSON), so there is no hand-built YAML to
    mis-quote and no YAML dependency in the cage.

The `kubectl` invocations themselves (mint, and deriving the server URL from
the active context) live in the launcher, where the user's kubeconfig, exec
plugins and client certs already work — reimplementing that auth in Python is
exactly the fragile surface this design avoids.
"""
import json
import sys
import urllib.parse

PLACEHOLDER_TOKEN = "tjor-broker-placeholder"


def normalize_server(server):
    """Canonical https URL for a kubeconfig server value.

    A kubeconfig server is normally a full URL (`https://host:6443`); a bare
    `host[:port]` override is accepted and assumed https. Without a scheme,
    urlparse would read the host as the scheme, so add one first.
    """
    s = (server or "").strip()
    if not s:
        raise ValueError("empty API server")
    if "://" not in s:
        s = "https://" + s
    return s


def api_host(server):
    """Host (no scheme, no port) of a kubeconfig cluster server URL."""
    host = urllib.parse.urlparse(normalize_server(server)).hostname
    if not host:
        raise ValueError(f"no host in API server URL: {server!r}")
    return host


def _server_identity(server):
    """Canonical ``(scheme, host, effective port)`` of a server URL — the one
    identity a server is judged by (#58). urlparse lowercases the hostname;
    a missing port takes the scheme's default (443 https, 80 http)."""
    parsed = urllib.parse.urlparse(normalize_server(server))
    host = parsed.hostname
    if not host:
        raise ValueError(f"no host in API server URL: {server!r}")
    return parsed.scheme, host, parsed.port or (80 if parsed.scheme == "http" else 443)


def api_origin(server):
    """Exact ``host:port`` origin of a kubeconfig cluster server URL (#49) —
    the kube broker's injection scope. Uses the URL's explicit port, else the
    scheme's default (443 https, 80 http); an IPv6 host is bracketed so the
    port suffix parses unambiguously."""
    _, host, port = _server_identity(server)
    return (f"[{host}]:{port}") if ":" in host else f"{host}:{port}"


def same_server(a, b):
    """True iff ``a`` and ``b`` name the same API server (#58): equal
    canonical identity, so a bare ``host:port`` `kube_api_host` pin and the
    kubeconfig's full URL compare equal, while a different host, port, or
    scheme does not."""
    return _server_identity(a) == _server_identity(b)


def kubeconfig(server, ca_path, token=PLACEHOLDER_TOKEN):
    """A minimal placeholder kubeconfig (JSON) for the caged kubectl.

    Points at the real `server`, trusts the session CA at `ca_path` (the proxy
    re-signs the API server's TLS), and carries only `token` — a placeholder by
    default, overwritten in flight by the proxy with the real SA token.
    """
    server = normalize_server(server)
    api_host(server)  # validate a host is present before we emit
    doc = {
        "apiVersion": "v1",
        "kind": "Config",
        "clusters": [
            {"name": "tjor", "cluster": {"server": server, "certificate-authority": ca_path}}
        ],
        "contexts": [{"name": "tjor", "context": {"cluster": "tjor", "user": "tjor"}}],
        "current-context": "tjor",
        "users": [{"name": "tjor", "user": {"token": token}}],
    }
    return json.dumps(doc, indent=2) + "\n"


def _main(argv):
    if len(argv) < 2:
        sys.exit("usage: tjor_kube.py {host|origin|url|same|config} ...")
    cmd = argv[1]
    try:
        if cmd == "host":  # host <server>
            print(api_host(argv[2]))
        elif cmd == "origin":  # origin <server>  -> host:port injection scope (#49)
            print(api_origin(argv[2]))
        elif cmd == "same":  # same <a> <b>  -> exit 0 iff the same API server (#58)
            sys.exit(0 if same_server(argv[2], argv[3]) else 1)
        elif cmd == "url":  # url <server>  -> canonical https URL
            print(normalize_server(argv[2]))
        elif cmd == "config":  # config <server> <ca_path> [token]
            sys.stdout.write(kubeconfig(*argv[2:5]) if len(argv) >= 5
                             else kubeconfig(argv[2], argv[3]))
        else:
            sys.exit(f"tjor_kube.py: unknown command {cmd!r}")
    except (IndexError, ValueError) as exc:
        sys.exit(f"tjor_kube.py: {exc}")


if __name__ == "__main__":
    _main(sys.argv)
