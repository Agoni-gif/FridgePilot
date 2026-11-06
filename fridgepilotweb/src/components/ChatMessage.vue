<script setup lang="ts">
import type { ChatMessageItem } from '../types/recipe'
import RecipeCard from './RecipeCard.vue'

defineProps<{
  item: ChatMessageItem
}>()
</script>

<template>
  <div class="row" :class="item.role">
    <div v-if="item.role === 'user'" class="bubble user">
      <div class="sheen" aria-hidden="true" />
      <p>{{ item.text }}</p>
    </div>

    <div v-else-if="item.role === 'status'" class="bubble status">
      <span class="pulse" aria-hidden="true">
        <span /><span /><span />
      </span>
      <span class="status-text">{{ item.text }}</span>
    </div>

    <div v-else-if="item.role === 'error'" class="bubble error">
      {{ item.text }}
    </div>

    <div v-else-if="item.recipe" class="assistant">
      <RecipeCard :recipe="item.recipe" />
    </div>

    <div v-else class="bubble assistant-text">
      <span class="quote" aria-hidden="true" />
      <p>{{ item.text }}</p>
    </div>
  </div>
</template>

<style scoped>
.row {
  display: flex;
  width: 100%;
  animation: pop 420ms var(--ease) both;
}

.row.user {
  justify-content: flex-end;
}

.row.status,
.row.error,
.row.assistant {
  justify-content: flex-start;
}

.bubble {
  position: relative;
  max-width: 100%;
  line-height: 1.6;
}

.bubble p {
  margin: 0;
}

.user {
  overflow: hidden;
  max-width: min(100%, 85%);
  padding: 0.85rem 1rem;
  border-radius: 14px 14px 4px 14px;
  background: var(--ink);
  color: #f3f5f8;
}

.sheen {
  position: absolute;
  inset: 0 auto auto 0;
  width: 55%;
  height: 45%;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.12), transparent 70%);
  pointer-events: none;
}

.status {
  display: inline-flex;
  align-items: center;
  gap: 0.85rem;
  padding: 0.75rem 1rem;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.62);
  border: 1px solid color-mix(in srgb, var(--line) 80%, white);
  color: var(--ink-soft);
  backdrop-filter: blur(8px);
}

.pulse {
  display: inline-flex;
  gap: 4px;
  align-items: center;
}

.pulse span {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--accent);
  animation: blink 1.1s ease-in-out infinite;
}

.pulse span:nth-child(2) {
  animation-delay: 0.15s;
}

.pulse span:nth-child(3) {
  animation-delay: 0.3s;
}

.status-text {
  font-size: 0.95rem;
}

.error {
  padding: 0.85rem 1rem;
  border-radius: 14px;
  background: var(--danger-wash);
  color: var(--danger);
  border: 1px solid color-mix(in srgb, var(--danger) 18%, white);
}

.assistant-text {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.75rem;
  width: 100%;
  padding: 0.95rem 1rem;
  border-radius: 14px;
  background: #fff;
  border: 1px solid var(--line);
  color: var(--ink-soft);
}

.quote {
  width: 3px;
  border-radius: 3px;
  background: linear-gradient(180deg, var(--accent), color-mix(in srgb, var(--accent) 20%, transparent));
  margin: 0.15rem 0;
}

.assistant {
  width: 100%;
}

@keyframes pop {
  from {
    opacity: 0;
    transform: translateY(10px) scale(0.985);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes blink {
  0%,
  100% {
    opacity: 0.25;
    transform: translateY(0);
  }
  50% {
    opacity: 1;
    transform: translateY(-1px);
  }
}
</style>
