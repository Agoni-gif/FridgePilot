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

const confidenceLabel: Record<string, string> = {
  low: '偏低',
  medium: '中等',
  high: '较高',
}
</script>

<template>
  <article class="recipe">
    <header class="head">
      <div class="title-row">
        <h2>{{ recipe.title }}</h2>
        <span class="badge">可信度 {{ confidenceLabel[recipe.confidence] || recipe.confidence }}</span>
      </div>
      <p class="summary">{{ recipe.summary }}</p>
      <div class="meta">
        <span v-if="formatMinutes(recipe.prep_time_minutes)">准备 {{ formatMinutes(recipe.prep_time_minutes) }}</span>
        <span v-if="formatMinutes(recipe.cook_time_minutes)">烹饪 {{ formatMinutes(recipe.cook_time_minutes) }}</span>
        <span v-if="recipe.servings">约 {{ recipe.servings }} 人份</span>
      </div>
    </header>

    <div class="grid">
      <section>
        <h3>食材</h3>
        <ul class="ingredients">
          <li v-for="(item, i) in recipe.ingredients" :key="i">{{ item }}</li>
        </ul>
      </section>

      <section class="steps-section">
        <h3>步骤</h3>
        <ol class="steps">
          <li v-for="(step, i) in recipe.steps" :key="i">
            <span class="num">{{ i + 1 }}</span>
            <span>{{ step }}</span>
          </li>
        </ol>
      </section>
    </div>

    <section v-if="recipe.tips?.length" class="tips-section">
      <h3>小贴士</h3>
      <ul class="tips">
        <li v-for="(tip, i) in recipe.tips" :key="i">{{ tip }}</li>
      </ul>
    </section>

    <RecipeSources :sources="recipe.sources" />
  </article>
</template>

<style scoped>
.recipe {
  display: grid;
  gap: 1.25rem;
  padding: 1.25rem 1.3rem 1.35rem;
  border-radius: var(--radius);
  background: var(--panel-solid);
  border: 1px solid var(--line);
  border-top: 3px solid var(--accent);
}

.head {
  display: grid;
  gap: 0.55rem;
}

.title-row {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 0.85rem;
}

h2 {
  margin: 0;
  font-family: var(--font-display);
  font-weight: 700;
  font-size: clamp(1.35rem, 3.5vw, 1.7rem);
  line-height: 1.2;
  letter-spacing: -0.02em;
  color: var(--ink);
}

.badge {
  flex-shrink: 0;
  margin-top: 0.2rem;
  font-size: 0.75rem;
  letter-spacing: 0.04em;
  color: var(--accent-deep);
  background: var(--accent-wash);
  border: 1px solid color-mix(in srgb, var(--accent) 35%, transparent);
  border-radius: 8px;
  padding: 0.28rem 0.5rem;
}

.summary {
  margin: 0;
  color: var(--ink-soft);
  line-height: 1.55;
}

.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem 1rem;
  font-size: 0.88rem;
  color: var(--muted);
}

.grid {
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.2fr);
  gap: 1.25rem 1.5rem;
}

h3 {
  margin: 0 0 0.7rem;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
}

.ingredients,
.tips {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 0.45rem;
}

.ingredients li {
  padding-left: 0.85rem;
  position: relative;
  line-height: 1.5;
}

.ingredients li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0.55em;
  width: 0.35rem;
  height: 0.35rem;
  background: var(--accent);
}

.steps {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 0.75rem;
}

.steps li {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.7rem;
  align-items: start;
  line-height: 1.55;
}

.num {
  width: 1.55rem;
  height: 1.55rem;
  display: grid;
  place-items: center;
  border-radius: 8px;
  background: var(--ink);
  color: #f7f8fa;
  font-size: 0.78rem;
  font-weight: 700;
}

.tips li {
  color: var(--ink-soft);
  line-height: 1.5;
}

@media (max-width: 720px) {
  .grid {
    grid-template-columns: 1fr;
  }

  .title-row {
    flex-direction: column;
  }
}
</style>
