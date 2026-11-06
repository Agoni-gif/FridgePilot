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
          {{ source.title || source.url }}
        </a>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.sources {
  padding-top: 0.35rem;
}

h3 {
  margin: 0 0 0.45rem;
  font-size: 0.95rem;
  font-weight: 650;
}

ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 0.35rem;
}

a {
  color: var(--brand);
  text-decoration: none;
  word-break: break-word;
  line-height: 1.45;
}

a:hover {
  text-decoration: underline;
}
</style>
