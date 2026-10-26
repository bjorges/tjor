<script setup lang="ts">
// The cage topology. The launcher creates the internal-only agent network
// (compose marks it external) and attaches the sidecars: a dual-homed explicit
// proxy as the only crossing, a dual-homed DNS sidecar that forwards allowed
// zones to an upstream resolver and answers NXDOMAIN for the rest, an optional
// gateway on the egress side; brokered credentials and identity applied at the
// proxy, never inside the agent. Colors come from the shared tokens. Every
// text must fit its box: the render check measures them (slides/agents.md).
</script>

<template>
  <svg class="topo" viewBox="0 0 960 440" role="img" aria-label="tjor cage topology">
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
      <rect x="20" y="40" width="470" height="360" rx="14" />
      <text x="36" y="66" class="netlabel">
        internal-only network · no route off it, by topology
      </text>
    </g>
    <g class="net egress">
      <rect x="520" y="40" width="420" height="360" rx="14" />
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

    <!-- proxy, dual-homed: straddles both networks -->
    <g class="box proxy">
      <rect x="400" y="96" width="210" height="120" rx="10" />
      <text x="416" y="122" class="title">egress proxy</text>
      <text x="416" y="142" class="line small">dual-homed · terminates TLS</text>
      <text x="416" y="160" class="line small">host → path → default deny</text>
      <text x="416" y="178" class="line small">injects brokered credential</text>
      <text x="416" y="196" class="line small">forged identity out, real in</text>
    </g>

    <!-- dns sidecar, dual-homed like the proxy -->
    <g class="box side">
      <rect x="400" y="250" width="210" height="80" rx="10" />
      <text x="416" y="274" class="title small">DNS sidecar · dual-homed</text>
      <text x="416" y="294" class="line small">allowed zones: forwarded</text>
      <text x="416" y="312" class="line small">anything else: NXDOMAIN, locally</text>
    </g>

    <!-- internet -->
    <g class="box world">
      <rect x="700" y="96" width="220" height="120" rx="10" />
      <text x="716" y="122" class="title">allow-listed hosts</text>
      <text x="716" y="142" class="line small">source hosting · registries</text>
      <text x="716" y="160" class="line small">LLM endpoints · your cluster API</text>
      <text x="716" y="186" class="line small deny">everything else: denied</text>
    </g>

    <!-- gateway, egress side only -->
    <g class="box side">
      <rect x="700" y="250" width="220" height="56" rx="10" />
      <text x="716" y="272" class="title small">LLM gateway (optional)</text>
      <text x="716" y="292" class="line small">inference paths only · admin denied</text>
    </g>

    <!-- the DNS sidecar's upstream -->
    <g class="box side">
      <rect x="700" y="330" width="220" height="56" rx="10" />
      <text x="716" y="352" class="title small">upstream resolver</text>
      <text x="716" y="372" class="line small">forwarded allowed-zone queries</text>
    </g>

    <!-- arrows: agent → proxy, proxy → hosts, agent → DNS, DNS → upstream,
         proxy → gateway, gateway → providers; none crosses a box or another -->
    <g class="edges">
      <path d="M312 150 H398" marker-end="url(#arrow)" />
      <path d="M610 150 H698" marker-end="url(#arrow)" />
      <path d="M312 290 H398" marker-end="url(#arrow)" />
      <path d="M610 300 C 650 300, 650 358, 698 358" class="dashed" marker-end="url(#arrow)" />
      <path
        d="M560 216 C 560 236, 660 236, 660 278 H 698"
        class="dashed"
        marker-end="url(#arrow)"
      />
      <path d="M880 248 V 218" class="dashed" marker-end="url(#arrow)" />
      <text x="872" y="238" class="edge" text-anchor="end">providers</text>
      <!-- the impossible path -->
      <path d="M170 292 V 410 Q 170 420 180 420 H 940 Q 950 420 950 410 V 150" class="blocked" />
      <text x="300" y="413" class="edge blocked">direct egress: no route exists</text>
    </g>

    <!-- host -->
    <g class="host">
      <text x="24" y="16" class="hostlabel">
        host: tjor run — creates the internal-only network, resolves mounts, refuses sensitive
        paths,
      </text>
      <text x="24" y="31" class="hostlabel">
        baselines git metadata, mints short-TTL credentials for the proxy
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
