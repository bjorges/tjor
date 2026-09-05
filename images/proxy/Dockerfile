# syntax=docker/dockerfile:1
# tjor egress proxy: pinned mitmproxy base + the policy addon.
# BASE_IMAGE is default-less on purpose (charter L8): the launcher supplies
# the digest-pinned reference from config/tjor.toml.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

COPY proxy/addon.py python/tjor_policy.py python/tjor_identity.py python/tjor_broker.py /addon/
# The broker signs GitHub App JWTs with `cryptography`, which the mitmproxy
# base image already bundles for its own TLS — no extra install needed.
COPY proxy/entrypoint.sh /usr/local/bin/tjor-proxy-entrypoint
RUN chmod 0755 /usr/local/bin/tjor-proxy-entrypoint

ENV TJOR_POLICY_FILE=/policy/policy.toml
ENTRYPOINT ["/usr/local/bin/tjor-proxy-entrypoint"]
