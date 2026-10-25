<script setup lang="ts">
// The cage, as compose builds it: an internal-only agent network with no
// route out; a dual-homed explicit proxy as the only crossing; a DNS sidecar
// that answers NXDOMAIN for anything outside the allowed zones; an optional
// gateway on the egress side; brokered credentials and identity applied at
// the proxy, never inside the agent. Colors come from the shared tokens.
</script>

<template>
  <svg class="topo" viewBox="0 0 960 420" role="img" aria-label="tjor cage topology">
    <defs>
      <marker
        id="arrow"
        viewBox="0 0 10 10"
        refX="9"
        refY="5"
        markerWidth="7"
        markerHeight="7"
        orient="auto-start-reverse"
      >
        <path d="M0 0 L10 5 L0 10 z" fill="currentColor" />
      </marker>
    </defs>

    <!-- networks -->
    <g class="net internal">
      <rect x="20" y="40" width="470" height="300" rx="14" />
      <text x="36" y="66" class="netlabel">
        internal-only network · no route off it, by topology
      </text>
    </g>
    <g class="net egress">
      <rect x="520" y="40" width="420" height="300" rx="14" />
      <text x="536" y="66" class="netlabel">egress network</text>
    </g>

    <!-- agent container -->
    <g class="box agent">
      <rect x="44" y="92" width="268" height="200" rx="10" />
      <text x="60" y="118" class="title">agent container</text>
      <text x="60" y="142" class="line">opencode · Claude Code · Copilot CLI</text>
      <text x="60" y="162" class="line">non-root user · uid aligned to host</text>
      <text x="60" y="182" class="line">repo mounts · per-session state</text>
      <text x="60" y="202" class="line">Landlock allowlist · masked .env / hooks</text>
      <text x="60" y="228" class="line emph">credentials: placeholder only</text>
      <text x="60" y="248" class="line emph">identity: TJOR_SESSION_ID …</text>
      <text x="60" y="276" class="line muted">HTTP(S)_PROXY → the proxy, explicitly</text>
    </g>

    <!-- dns sidecar -->
    <g class="box side">
      <rect x="330" y="236" width="150" height="80" rx="10" />
      <text x="346" y="260" class="title small">DNS sidecar</text>
      <text x="346" y="280" class="line small">allowed zones: forward</text>
      <text x="346" y="298" class="line small">anything else: NXDOMAIN</text>
    </g>

    <!-- proxy, dual-homed: straddles both networks -->
    <g class="box proxy">
      <rect x="400" y="96" width="210" height="120" rx="10" />
      <text x="416" y="122" class="title">egress proxy</text>
      <text x="416" y="142" class="line small">dual-homed · fail-closed allowlist</text>
      <text x="416" y="160" class="line small">host → path → default deny</text>
      <text x="416" y="178" class="line small">injects brokered credential</text>
      <text x="416" y="196" class="line small">strips forged identity, injects real</text>
    </g>

    <!-- gateway -->
    <g class="box side">
      <rect x="650" y="236" width="150" height="80" rx="10" />
      <text x="666" y="260" class="title small">LLM gateway (opt.)</text>
      <text x="666" y="280" class="line small">inference paths only</text>
      <text x="666" y="298" class="line small">admin API: denied</text>
    </g>

    <!-- internet -->
    <g class="box world">
      <rect x="700" y="96" width="220" height="120" rx="10" />
      <text x="716" y="122" class="title">allow-listed hosts</text>
      <text x="716" y="142" class="line small">source hosting · registries</text>
      <text x="716" y="160" class="line small">LLM endpoints · your cluster API</text>
      <text x="716" y="186" class="line small deny">everything else: denied</text>
    </g>

    <!-- arrows -->
    <g class="edges">
      <path d="M312 150 H398" marker-end="url(#arrow)" />
      <path d="M610 150 H698" marker-end="url(#arrow)" />
      <path d="M312 276 H328" marker-end="url(#arrow)" />
      <path
        d="M480 276 C 520 276, 520 300, 560 300 H 600"
        class="dashed"
        marker-end="url(#arrow)"
      />
      <text x="498" y="334" class="edge">allowed zones only</text>
      <path d="M560 216 C 560 236, 600 236, 648 262" class="dashed" marker-end="url(#arrow)" />
      <text x="508" y="252" class="edge">inference only</text>
      <!-- the impossible path -->
      <path d="M170 292 C 170 380, 760 380, 790 216" class="blocked" />
      <text x="360" y="398" class="edge blocked">direct egress: no route exists</text>
    </g>

    <!-- host -->
    <g class="host">
      <text x="24" y="20" class="hostlabel">
        host: tjor run — resolves mounts, refuses sensitive paths, baselines git metadata, mints
        short-TTL credentials for the proxy
      </text>
    </g>
  </svg>
</template>

<style scoped>
.topo {
  width: 100%;
  height: 100%;
  font-family: 'Inter', sans-serif;
}
.net rect {
  fill: var(--tjor-surface);
  stroke: var(--tjor-line);
  stroke-width: 1;
}
.net.internal rect {
  stroke: var(--tjor-teal);
  stroke-dasharray: 6 5;
}
.netlabel {
  font-family: var(--slidev-code-font-family, monospace);
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  fill: var(--tjor-muted);
}
.net.internal .netlabel {
  fill: var(--tjor-teal);
}
.box rect {
  fill: var(--tjor-surface-2);
  stroke: var(--tjor-line);
}
.box.agent rect {
  stroke: var(--tjor-teal);
  stroke-width: 1.5;
}
.box.proxy rect {
  fill: var(--tjor-ground);
  stroke: var(--tjor-accent);
  stroke-width: 2;
}
.title {
  font-size: 15px;
  font-weight: 700;
  fill: var(--tjor-ink);
}
.title.small {
  font-size: 13px;
}
.line {
  font-size: 12.5px;
  fill: var(--tjor-ink);
}
.line.small {
  font-size: 11.5px;
}
.line.muted {
  fill: var(--tjor-muted);
}
.line.emph {
  fill: var(--tjor-accent);
}
.line.deny {
  fill: var(--tjor-problem);
  font-weight: 600;
}
.edges path {
  fill: none;
  stroke: var(--tjor-ink);
  stroke-width: 1.8;
  color: var(--tjor-ink);
}
.edges path.dashed {
  stroke-dasharray: 5 4;
  stroke: var(--tjor-muted);
  color: var(--tjor-muted);
}
.edges path.blocked {
  stroke: var(--tjor-problem);
  stroke-dasharray: 3 6;
  stroke-width: 2;
  opacity: 0.85;
}
.edge {
  font-family: var(--slidev-code-font-family, monospace);
  font-size: 10.5px;
  fill: var(--tjor-muted);
}
.edge.blocked {
  fill: var(--tjor-problem);
}
.hostlabel {
  font-family: var(--slidev-code-font-family, monospace);
  font-size: 10.5px;
  fill: var(--tjor-muted);
}
</style>
