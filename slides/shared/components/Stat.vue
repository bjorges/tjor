<script setup lang="ts">
// A single figure with its label. Prefer `fact` over `value`: facts are
// build-time constants (VERSION, boundary matrix, specs, ADRs) so the figure
// can never go stale. Markdown template expressions cannot see the __TJOR_*__
// constants (Vue prefixes them with _ctx.), which is why they resolve here.
import { computed } from 'vue'

const props = defineProps<{
  fact?: 'version' | 'checks' | 'guarantees' | 'specs' | 'adrs'
  value?: string | number
  label: string
  hint?: string
}>()

const facts: Record<string, string> = {
  version: __TJOR_VERSION__,
  checks: String(__TJOR_CHECKS__),
  guarantees: String(__TJOR_GUARANTEES__),
  specs: String(__TJOR_SPECS__.length),
  adrs: String(__TJOR_ADR_COUNT__),
}

const shown = computed(() => (props.fact ? facts[props.fact] : String(props.value ?? '')))
</script>

<template>
  <div class="tjor-stat">
    <div class="value">{{ shown }}</div>
    <div class="label">{{ label }}</div>
    <div v-if="hint" class="hint">{{ hint }}</div>
  </div>
</template>

<style scoped>
.tjor-stat {
  background: var(--tjor-surface);
  border: 1px solid var(--tjor-line-soft);
  border-top: 3px solid var(--tjor-teal);
  border-radius: 10px;
  padding: 0.8rem 1rem 0.7rem;
  box-shadow: var(--tjor-shadow);
}
.value {
  font-size: 2.1rem;
  font-weight: 700;
  line-height: 1;
  letter-spacing: -0.02em;
  color: var(--tjor-ink);
}
.label {
  margin-top: 0.4rem;
  font-size: 0.82rem;
  color: var(--tjor-ink);
}
.hint {
  margin-top: 0.15rem;
  font-family: var(--slidev-code-font-family, monospace);
  font-size: 0.62rem;
  color: var(--tjor-muted);
}
</style>
