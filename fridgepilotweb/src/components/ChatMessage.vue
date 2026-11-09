<script setup lang="ts">
import type { ChatMessageItem } from '../types/recipe'
import RecipeCard from './RecipeCard.vue'
import ThinkingPanel from './ThinkingPanel.vue'

defineProps<{
  item: ChatMessageItem
}>()
</script>

<template>
  <div class="row" :class="item.role">
    <template v-if="item.role === 'user'">
      <div class="user-bubble">
        <p>{{ item.text }}</p>
      </div>
    </template>

    <template v-else-if="item.role === 'status'">
      <div class="assistant-block">
        <ThinkingPanel v-if="item.thinking" :thinking="item.thinking" />
        <div v-else class="status">
          <span class="dots" aria-hidden="true"><i /><i /><i /></span>
          <span>{{ item.text }}</span>
        </div>
      </div>
    </template>

    <template v-else-if="item.role === 'divider'">
      <div class="divider" role="separator">
        <span>{{ item.text || '已重新开始，之前的聊天不再作为本次参考' }}</span>
      </div>
    </template>

    <template v-else-if="item.role === 'error'">
      <div class="assistant-block">
        <ThinkingPanel v-if="item.thinking" :thinking="item.thinking" />
        <div class="error">{{ item.text }}</div>
      </div>
    </template>

    <template v-else-if="item.recipe">
      <div class="assistant-block">
        <ThinkingPanel v-if="item.thinking" :thinking="item.thinking" />
        <div class="body">
          <RecipeCard :recipe="item.recipe" />
        </div>
      </div>
    </template>

    <template v-else>
      <div class="assistant-block">
        <ThinkingPanel v-if="item.thinking" :thinking="item.thinking" />
        <div class="body plain">
          <p>{{ item.text }}</p>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.row {
  width: 100%;
  margin: 0 0 1.35rem;
  animation: rise 320ms var(--ease) both;
}

.row.user {
  display: flex;
  justify-content: flex-end;
}

.row.status,
.row.assistant,
.row.error,
.row.divider {
  display: block;
}

.assistant-block {
  width: 100%;
  min-width: 0;
}

.user-bubble {
  max-width: min(100%, 78%);
  padding: 0.75rem 1rem;
  border-radius: 18px;
  background: var(--user-bubble);
  color: var(--ink);
  line-height: 1.6;
}

.user-bubble p,
.plain p {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
}

.body {
  min-width: 0;
  line-height: 1.7;
  color: var(--ink);
  font-size: 0.98rem;
}

.status {
  display: inline-flex;
  align-items: center;
  gap: 0.55rem;
  min-height: 2rem;
  color: var(--muted);
  font-size: 0.92rem;
}

.dots {
  display: inline-flex;
  gap: 3px;
}

.dots i {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--muted);
  animation: blink 1.1s ease-in-out infinite;
}

.dots i:nth-child(2) {
  animation-delay: 0.15s;
}

.dots i:nth-child(3) {
  animation-delay: 0.3s;
}

.error {
  padding: 0.7rem 0.85rem;
  border-radius: 12px;
  background: var(--danger-wash);
  color: var(--danger);
  line-height: 1.55;
}

.divider {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin: 0.35rem 0 0.85rem;
  color: var(--muted);
  font-size: 0.78rem;
}

.divider::before,
.divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--line);
}

.divider span {
  white-space: nowrap;
}

@keyframes rise {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes blink {
  0%,
  100% {
    opacity: 0.25;
  }
  50% {
    opacity: 1;
  }
}
</style>
