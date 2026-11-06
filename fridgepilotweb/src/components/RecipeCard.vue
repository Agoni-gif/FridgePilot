<script setup lang="ts">
import type { Recipe } from '../types/recipe'
import RecipeSources from './RecipeSources.vue'

defineProps<{
  recipe: Recipe
}>()

function formatMinutes(value: number | null | undefined): string | null {
  if (value == null) return null
  return `${value} 分钟`
}
</script>

<template>
  <article class="recipe">
    <h2>{{ recipe.title }}</h2>
    <p class="summary">{{ recipe.summary }}</p>

    <p class="meta">
      <span v-if="formatMinutes(recipe.prep_time_minutes)">准备 {{ formatMinutes(recipe.prep_time_minutes) }}</span>
      <span v-if="formatMinutes(recipe.cook_time_minutes)">烹饪 {{ formatMinutes(recipe.cook_time_minutes) }}</span>
      <span v-if="recipe.servings">约 {{ recipe.servings }} 人份</span>
    </p>

    <section>
      <h3>食材</h3>
      <ul>
        <li v-for="(item, i) in recipe.ingredients" :key="i">{{ item }}</li>
      </ul>
    </section>

    <section>
      <h3>步骤</h3>
      <ol>
        <li v-for="(step, i) in recipe.steps" :key="i">{{ step }}</li>
      </ol>
    </section>

    <section v-if="recipe.tips?.length">
      <h3>小贴士</h3>
      <ul>
        <li v-for="(tip, i) in recipe.tips" :key="i">{{ tip }}</li>
      </ul>
    </section>

    <RecipeSources :sources="recipe.sources" />
  </article>
</template>

<style scoped>
.recipe {
  display: grid;
  gap: 1rem;
}

h2 {
  margin: 0;
  font-size: 1.2rem;
  font-weight: 650;
  letter-spacing: -0.02em;
  line-height: 1.35;
}

.summary {
  margin: 0;
  color: var(--ink-soft);
  line-height: 1.65;
}

.meta {
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 0.9rem;
  color: var(--muted);
  font-size: 0.88rem;
}

h3 {
  margin: 0 0 0.45rem;
  font-size: 0.95rem;
  font-weight: 650;
}

ul,
ol {
  margin: 0;
  padding-left: 1.2rem;
  display: grid;
  gap: 0.4rem;
}

li {
  line-height: 1.65;
  color: var(--ink);
}

section + section {
  margin-top: 0.15rem;
}
</style>
