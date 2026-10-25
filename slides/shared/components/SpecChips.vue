<script setup lang="ts">
// Chips linking a slide to the OpenSpec capability (and ADR) it describes.
// A spec tag is `<capability>@<requirement count>` — the count is the pin
// tests/slides_consistency.sh checks (see slides/agents.md); only the name shows.
import { computed } from 'vue'

const props = defineProps<{ specs?: string[]; adrs?: string[] }>()

const repo = 'https://github.com/bjorges/tjor/blob/main'

const specChips = computed(() =>
  (props.specs ?? []).map((tag) => {
    const name = String(tag).split('@')[0]
    return { name, href: `${repo}/openspec/specs/${name}/spec.md` }
  }),
)

const adrChips = computed(() =>
  (props.adrs ?? []).map((n) => {
    const id = String(n).padStart(4, '0')
    const file = __TJOR_ADR_FILES__.find((f) => f.startsWith(`${id}-`))
    return {
      name: `ADR ${id}`,
      href: file ? `${repo}/docs/decisions/${file}` : `${repo}/docs/decisions`,
    }
  }),
)
</script>

<template>
  <div v-if="specChips.length || adrChips.length" class="tjor-chips">
    <a v-for="c in specChips" :key="c.href" class="tjor-chip spec" :href="c.href" target="_blank">
      {{ c.name }}
    </a>
    <a v-for="c in adrChips" :key="c.href" class="tjor-chip adr" :href="c.href" target="_blank">
      {{ c.name }}
    </a>
  </div>
</template>
