<script setup lang="ts">
// Build-time repository facts for use inside markdown: <Facts kind="version" />.
import { computed } from 'vue'

const props = defineProps<{ kind: 'version' | 'checks' | 'guarantees' | 'specs' | 'adrs' }>()

const text = computed(() => {
  switch (props.kind) {
    case 'version':
      return __TJOR_VERSION__
    case 'checks':
      return String(__TJOR_CHECKS__)
    case 'guarantees':
      return String(__TJOR_GUARANTEES__)
    case 'specs':
      return String(__TJOR_SPECS__.length)
    case 'adrs':
      return String(__TJOR_ADR_COUNT__)
  }
})
</script>

<template>
  <span>{{ text }}</span>
</template>
