<script setup lang="ts">
import type { RecipeSource } from '../types/recipe'

defineProps<{
  sources: RecipeSource[]
}>()
</script>

<template>
  <div class="sources">
    <h3>来源</h3>
    <ul>
      <li v-for="(source, index) in sources" :key="`${source.url}-${index}`">
        <a :href="source.url" target="_blank" rel="noopener noreferrer">
          <span class="idx">{{ String(index + 1).padStart(2, '0') }}</span>
          <span class="title">{{ source.title || source.url }}</span>
        </a>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.sources {
  padding-top: 0.35rem;
  border-top: 1px dashed var(--line);
}

h3 {
  margin: 0 0 0.65rem;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
}

ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 0.35rem;
}

a {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.65rem;
  align-items: baseline;
  text-decoration: none;
  color: var(--ink);
  padding: 0.35rem 0;
  transition: color 140ms ease;
}

a:hover {
  color: var(--accent-deep);
}

.idx {
  font-family: var(--font-display);
  font-size: 0.8rem;
  font-weight: 700;
  color: var(--accent-deep);
}

.title {
  word-break: break-word;
  border-bottom: 1px solid color-mix(in srgb, var(--accent) 40%, transparent);
  line-height: 1.4;
}
</style>
