<script setup lang="ts">
// The agenda: every problem the deck covers, grouped by theme. Kept as data so
// the map and the section order cannot drift apart silently in markup.
defineProps<{
  groups: { title: string; items: string[] }[]
}>()
</script>

<template>
  <div class="map">
    <div v-for="(g, i) in groups" :key="g.title" class="group">
      <div class="head">
        <span class="num">{{ String(i + 1).padStart(2, '0') }}</span>
        <span class="title">{{ g.title }}</span>
      </div>
      <ul>
        <li v-for="item in g.items" :key="item">{{ item }}</li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.map {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 0.8rem;
  height: 100%;
  align-content: center;
}
.group {
  background: var(--tjor-surface);
  border: 1px solid var(--tjor-line-soft);
  border-top: 3px solid var(--tjor-accent);
  border-radius: 10px;
  padding: 0.9rem 0.9rem 1rem;
  box-shadow: var(--tjor-shadow);
  min-height: 0;
}
.head {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  margin-bottom: 0.6rem;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid var(--tjor-line-soft);
}
.num {
  font-family: var(--slidev-code-font-family, monospace);
  font-size: 0.78rem;
  font-weight: 700;
  color: var(--tjor-accent);
}
.title {
  font-weight: 700;
  font-size: 1.05rem;
}
ul {
  padding-left: 1rem;
  margin: 0;
}
li {
  font-size: 0.86rem;
  line-height: 1.35;
  margin: 0.45rem 0;
  color: var(--tjor-ink);
}
</style>
