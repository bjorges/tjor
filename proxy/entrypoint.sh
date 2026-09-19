#!/bin/sh
# tjor proxy entrypoint. Replaces the base image's, whose group alignment
# (usermod -g <confdir gid>) crash-loops when the bind-mounted confdir's gid
# has no matching group inside the container (native Linux CI runners).
# Only the UID needs aligning: that is what grants the mitmproxy user read
# access to the launcher-generated CA key in the confdir.
set -eu

# Bound the OS resolver (#61). The base image is glibc, which honors
# RES_OPTIONS, so a hung/black-holed getaddrinfo returns within this wall time
# instead of the OS default — the guard's resolver workers (and mitmproxy's own
# upstream connect, same process) recover fast, so the resolver cap self-heals
# without a proxy restart. Small default; override via TJOR_PROXY_RES_OPTIONS,
# and an operator-supplied RES_OPTIONS is left untouched. Exported so the
# mitmproxy process (exec'd below, incl. via gosu/su-exec) inherits it.
: "${RES_OPTIONS:=${TJOR_PROXY_RES_OPTIONS:-timeout:1 attempts:2}}"
export RES_OPTIONS

DIR=/home/mitmproxy/.mitmproxy
mkdir -p "$DIR"

if [ "$(id -u)" = "0" ]; then
    owner_uid="$(stat -c %u "$DIR")"
    if [ "$owner_uid" != "0" ] && [ "$owner_uid" != "$(id -u mitmproxy)" ]; then
        usermod -o -u "$owner_uid" mitmproxy
    fi
    if command -v gosu >/dev/null 2>&1; then
        exec gosu mitmproxy "$@"
    fi
    if command -v su-exec >/dev/null 2>&1; then
        exec su-exec mitmproxy "$@"
    fi
    echo "tjor-proxy: neither gosu nor su-exec present — running as root (caps are dropped)" >&2
fi
exec "$@"
