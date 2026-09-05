#!/usr/bin/env python3
"""Pure helpers for the `kube` credential-broker source (#26).

The launcher mints a short-TTL Kubernetes ServiceAccount token host-side with
`kubectl create token` and hands it to the proxy as a `pat`-shaped credential,
injected as the bearer token toward the cluster API server host ONLY. The
agent holds only a placeholder; the real token never enters the cage.

These are the two PURE transforms that path needs, kept here (not inline in the
launcher/entrypoint) so they are unit-tested against the real code that runs:

  * `api_host(server)` — the host of a kubeconfig cluster server URL, used both
    as the broker's inject host and as the egress-allowlist target the operator
    must `tjor policy add`. Injection is host-scoped (port-agnostic, like the
    policy), so the host alone is the match key.
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
        sys.exit("usage: tjor_kube.py {host|url|config} ...")
    cmd = argv[1]
    try:
        if cmd == "host":  # host <server>
            print(api_host(argv[2]))
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
