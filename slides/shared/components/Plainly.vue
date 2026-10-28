<script setup lang="ts">
// "Stated plainly": the residual or trade-off a mechanism leaves — the deck
// states limits the way the README does. `proof` variant for evidence notes.
defineProps<{ tag?: string; proof?: boolean }>()
</script>

<template>
  <div class="tjor-callout" :class="{ proof }">
    <span class="tag">{{ tag ?? (proof ? 'Proven by' : 'Stated plainly') }}</span>
    <slot />
  </div>
</template>
