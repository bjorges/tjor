<script setup lang="ts">
// One problem, one answer: a problem panel and a "how tjor solves it" panel,
// with the backing spec/ADR chips in the header. Slots: ::problem:: ::solution::
import { useSlideContext } from '@slidev/client'
const { $frontmatter } = useSlideContext()
</script>

<template>
  <div class="slidev-layout problem">
    <SlideFrame
      :title="$frontmatter.title"
      :eyebrow="$frontmatter.eyebrow ?? 'Problem'"
      :specs="$frontmatter.specs"
      :adrs="$frontmatter.adrs"
    >
      <div class="tjor-cols">
        <section class="tjor-panel problem">
          <p class="tjor-eyebrow">The problem</p>
          <slot name="problem" />
        </section>
        <section class="tjor-panel solution">
          <p class="tjor-eyebrow">How tjor solves it</p>
          <slot name="solution" />
        </section>
      </div>
    </SlideFrame>
  </div>
</template>
