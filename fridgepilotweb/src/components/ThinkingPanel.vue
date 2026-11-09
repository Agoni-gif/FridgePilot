<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { ThinkingState } from '../types/recipe'

const props = defineProps<{
  thinking: ThinkingState
}>()

const open = ref(Boolean(props.thinking.defaultOpen ?? props.thinking.running))

watch(
  () => props.thinking.running,
  (running, wasRunning) => {
    if (running) open.value = true
    else if (wasRunning) open.value = Boolean(props.thinking.content)
  },
)

watch(
  () => props.thinking.defaultOpen,
  (value) => {
    if (value != null) open.value = value
  },
)

const title = computed(() => {
  if (props.thinking.running) return '思考中'
  const ms = props.thinking.elapsedMs
  if (ms != null && ms > 0) {
    const sec = Math.max(1, Math.round(ms / 1000))
    return `已深度思考（用时 ${sec} 秒）`
  }
  return '已深度思考'
})

const hasBody = computed(
  () => props.thinking.running || Boolean(props.thinking.content?.trim()),
)
</script>

<template>
  <div v-if="hasBody" class="think" :class="{ running: thinking.running, open }">
    <button type="button" class="think-toggle" :aria-expanded="open" @click="open = !open">
      <span class="chevron" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="14" height="14">
          <path fill="currentColor" d="M8.12 9.29 12 13.17l3.88-3.88L17.3 10.7 12 16l-5.3-5.3z" />
        </svg>
      </span>
      <span v-if="thinking.running" class="pulse" aria-hidden="true" />
      <span class="think-title">{{ title }}</span>
    </button>

    <div v-show="open" class="think-body">
      <p class="content">{{ thinking.content || '模型正在分析你的输入…' }}</p>
    </div>
  </div>
</template>

<style scoped>
.think {
  display: block;
  width: 100%;
  margin: 0 0 0.85rem;
  max-width: 100%;
  box-sizing: border-box;
}

.think-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  border: 0;
  background: transparent;
  padding: 0.15rem 0;
  color: var(--muted);
  font-size: 0.88rem;
  cursor: pointer;
  border-radius: 6px;
}

.think-toggle:hover {
  color: var(--ink-soft);
}

.chevron {
  display: grid;
  place-items: center;
  transition: transform 180ms var(--ease);
  color: var(--muted);
}

.think.open .chevron {
  transform: rotate(180deg);
}

.think-title {
  font-weight: 400;
  letter-spacing: -0.01em;
}

.pulse {
  width: 0.45rem;
  height: 0.45rem;
  border-radius: 50%;
  background: var(--brand);
  box-shadow: 0 0 0 0 color-mix(in srgb, var(--brand) 55%, transparent);
  animation: pulse 1.4s ease-out infinite;
}

.think-body {
  margin-top: 0.55rem;
  padding: 0.15rem 0 0.25rem 0.85rem;
  border-left: 2px solid var(--line);
  margin-left: 0.35rem;
  color: var(--muted);
  font-size: 0.9rem;
  line-height: 1.7;
  animation: fade 220ms var(--ease) both;
}

.content,
.placeholder {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
}

.placeholder {
  color: #b0b0b0;
}

@keyframes pulse {
  0% {
    box-shadow: 0 0 0 0 color-mix(in srgb, var(--brand) 45%, transparent);
  }
  70% {
    box-shadow: 0 0 0 8px transparent;
  }
  100% {
    box-shadow: 0 0 0 0 transparent;
  }
}

@keyframes fade {
  from {
    opacity: 0;
    transform: translateY(-2px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
