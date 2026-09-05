# syntax=docker/dockerfile:1
# tjor agent image. All versions and digests arrive as build args from
# config/tjor.toml via the launcher — nothing version-shaped is hardcoded
# here (charter L8), and every binary download passes a checksum gate before
# unpacking (charter L23; threat model documented in config/tjor.toml).
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git openssh-client jq ripgrep less procps \
        gosu python3 unzip \
    && rm -rf /var/lib/apt/lists/*

ARG TARGETARCH

# gh from the official release, sha256-gated. Not the distro package: Debian's
# build sends a trailing-space User-Agent that strict HTTP/2 proxies reject.
ARG GH_VERSION
ARG GH_SHA256_ARM64
ARG GH_SHA256_AMD64
RUN set -eu; \
    case "${TARGETARCH:-}" in \
        arm64) gh_arch="arm64"; gh_sha="${GH_SHA256_ARM64}" ;; \
        *) gh_arch="amd64"; gh_sha="${GH_SHA256_AMD64}" ;; \
    esac; \
    [ -n "${GH_VERSION}" ] && [ -n "${gh_sha}" ] || { echo "missing gh version/sha build args" >&2; exit 1; }; \
    curl -fsSLo /tmp/gh.tgz \
        "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${gh_arch}.tar.gz"; \
    echo "${gh_sha}  /tmp/gh.tgz" | sha256sum -c -; \
    tar -C /tmp -xzf /tmp/gh.tgz; \
    install -m 0755 "/tmp/gh_${GH_VERSION}_linux_${gh_arch}/bin/gh" /usr/local/bin/gh; \
    rm -rf /tmp/gh.tgz "/tmp/gh_${GH_VERSION}_linux_${gh_arch}"

# kubectl for the kube credential-broker source (#26), sha256-gated. Official
# dl.k8s.io binary (not a tarball — the .sha256 is over the binary itself).
# Present unconditionally so any harness can talk to a cluster; only used when
# the kube broker is active (the entrypoint writes a placeholder kubeconfig).
ARG KUBECTL_VERSION
ARG KUBECTL_SHA256_ARM64
ARG KUBECTL_SHA256_AMD64
RUN set -eu; \
    case "${TARGETARCH:-}" in \
        arm64) karch="arm64"; ksha="${KUBECTL_SHA256_ARM64}" ;; \
        *) karch="amd64"; ksha="${KUBECTL_SHA256_AMD64}" ;; \
    esac; \
    [ -n "${KUBECTL_VERSION}" ] && [ -n "${ksha}" ] || { echo "missing kubectl version/sha build args" >&2; exit 1; }; \
    curl -fsSLo /tmp/kubectl \
        "https://dl.k8s.io/release/v${KUBECTL_VERSION}/bin/linux/${karch}/kubectl"; \
    echo "${ksha}  /tmp/kubectl" | sha256sum -c -; \
    install -m 0755 /tmp/kubectl /usr/local/bin/kubectl; \
    rm -f /tmp/kubectl

# No X in the cage: make gh (and friends) print auth URLs instead of failing
# to exec a browser.
ENV BROWSER=echo

# HARNESS is a comma list: any of opencode, claude, copilot.
ARG HARNESS=opencode

# --- opencode: single binary from GitHub releases, sha256-gated -------------
ARG OPENCODE_VERSION
ARG OPENCODE_SHA256_ARM64
ARG OPENCODE_SHA256_X64
RUN set -eu; \
    case ",${HARNESS}," in *,opencode,*) \
        case "${TARGETARCH}" in \
            arm64) asset="opencode-linux-arm64.tar.gz"; sha="${OPENCODE_SHA256_ARM64}" ;; \
            amd64) asset="opencode-linux-x64.tar.gz"; sha="${OPENCODE_SHA256_X64}" ;; \
            *) echo "unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
        esac; \
        [ -n "${OPENCODE_VERSION}" ] && [ -n "${sha}" ] || { echo "missing opencode version/sha build args" >&2; exit 1; }; \
        curl -fsSLo /tmp/opencode.tgz \
            "https://github.com/anomalyco/opencode/releases/download/v${OPENCODE_VERSION}/${asset}"; \
        echo "${sha}  /tmp/opencode.tgz" | sha256sum -c -; \
        mkdir -p /tmp/oc; tar -C /tmp/oc -xzf /tmp/opencode.tgz; \
        bin="$(find /tmp/oc -type f -name opencode | head -1)"; \
        [ -n "${bin}" ] || { echo "opencode binary not found in archive" >&2; exit 1; }; \
        install -m 0755 "${bin}" /usr/local/bin/opencode; \
        rm -rf /tmp/opencode.tgz /tmp/oc ;; \
    esac

# --- claude / copilot: npm, exact-version pinned ----------------------------
ARG CLAUDE_CODE_VERSION
ARG COPILOT_VERSION
RUN set -eu; \
    case ",${HARNESS}," in \
        *,claude,*|*,copilot,*) \
            apt-get update && apt-get install -y --no-install-recommends nodejs npm \
            && rm -rf /var/lib/apt/lists/* ;; \
    esac; \
    case ",${HARNESS}," in *,claude,*) \
        [ -n "${CLAUDE_CODE_VERSION}" ] || { echo "missing CLAUDE_CODE_VERSION" >&2; exit 1; }; \
        npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" ;; \
    esac; \
    case ",${HARNESS}," in *,copilot,*) \
        [ -n "${COPILOT_VERSION}" ] || { echo "missing COPILOT_VERSION" >&2; exit 1; }; \
        npm install -g "@github/copilot@${COPILOT_VERSION}" ;; \
    esac

# Match the host user's uid so bind-mounted session state stays writable.
# Fixed default uid — the image is uid-AGNOSTIC (so one published image works
# for any host user). The entrypoint aligns the agent user to the host uid at
# container start (TJOR_AGENT_UID). 10001 is unlikely to collide.
ARG AGENT_UID=10001
RUN useradd -m -u ${AGENT_UID} -s /bin/bash agent

COPY images/agent/instructions/ /opt/tjor/instructions/
# tjor_kube.py (#26): the entrypoint renders the placeholder kubeconfig with
# the SAME tested code the launcher uses to derive the API host — one source of
# truth, not a re-implementation inline in the entrypoint.
COPY python/tjor_kube.py /opt/tjor/python/tjor_kube.py
COPY images/agent/entrypoint.sh /usr/local/bin/tjor-entrypoint
RUN chmod 0755 /usr/local/bin/tjor-entrypoint

ENV TJOR_CAGE=1
ENTRYPOINT ["/usr/local/bin/tjor-entrypoint"]
CMD ["opencode"]
