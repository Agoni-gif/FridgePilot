<script setup lang="ts">
import { computed, ref } from 'vue'
import type { PublicContext } from '../types/recipe'

const props = defineProps<{
  context: PublicContext | null
  busy?: boolean
}>()

const emit = defineEmits<{
  clear: []
}>()

const open = ref(false)

const hasState = computed(() => {
  const state = props.context?.state
  if (!state) return false
  return (
    state.ingredients.length > 0 ||
    state.servings != null ||
    state.max_time_minutes != null ||
    (state.dietary_restrictions?.length ?? 0) > 0 ||
    !!state.meal ||
    !!state.cuisine
  )
})

const ingredientText = computed(() => {
  const items = props.context?.state?.ingredients ?? []
  return items
    .map((i) => (i.quantity ? `${i.name} ${i.quantity}` : i.name))
    .join('、')
})

const summaryHint = computed(() => {
  const parts: string[] = []
  if (ingredientText.value) parts.push(ingredientText.value)
  const servings = props.context?.state?.servings
  if (servings != null) parts.push(`${servings}人`)
  const mins = props.context?.state?.max_time_minutes
  if (mins != null) parts.push(`${mins}分钟`)
  const diet = props.context?.state?.dietary_restrictions ?? []
  if (diet.length) parts.push(diet.join('、'))
  const text = parts.join(' · ')
  return text.length > 36 ? `${text.slice(0, 35)}…` : text
})

function onClear() {
  if (props.busy) return
  const ok = window.confirm(
    '清除本对话的做饭上下文？\n旧消息仍可阅读，但之后不再作为本次参考。\n长期做饭偏好不会被删除；若已启用，下一轮仍可能重新应用。',
  )
  if (ok) emit('clear')
}
</script>

<template>
  <div class="panel">
    <button type="button" class="toggle" @click="open = !open">
      <span>当前做饭条件</span>
      <span class="hint" v-if="hasState && !open">{{ summaryHint }}</span>
      <span class="chev" :class="{ open }">▾</span>
    </button>
    <div v-if="open" class="body">
      <template v-if="hasState && context?.state">
        <p v-if="ingredientText"><span class="label">食材</span>{{ ingredientText }}</p>
        <p v-if="context.state.servings != null">
          <span class="label">人数</span>{{ context.state.servings }} 人
        </p>
        <p v-if="context.state.max_time_minutes != null">
          <span class="label">时间</span>{{ context.state.max_time_minutes }} 分钟内
        </p>
        <p v-if="context.state.meal"><span class="label">餐次</span>{{ context.state.meal }}</p>
        <p v-if="context.state.cuisine"><span class="label">菜系</span>{{ context.state.cuisine }}</p>
        <p v-if="context.state.dietary_restrictions?.length">
          <span class="label">忌口</span>{{ context.state.dietary_restrictions.join('、') }}
        </p>
      </template>
      <p v-else class="empty">暂无已确认的做饭条件</p>
      <button type="button" class="clear" :disabled="busy || !context" @click="onClear">
        清除本对话上下文
      </button>
    </div>
  </div>
</template>

<style scoped>
.panel {
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--bg-soft) 70%, var(--bg));
}

.toggle {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  border: 0;
  background: transparent;
  padding: 0.55rem 1rem;
  color: var(--ink-soft);
  font-size: 0.82rem;
  cursor: pointer;
}

.hint {
  flex: 1;
  min-width: 0;
  text-align: left;
  color: var(--muted);
  font-size: 0.78rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chev {
  margin-left: auto;
  transition: transform 160ms ease;
  opacity: 0.7;
}

.chev.open {
  transform: rotate(180deg);
}

.body {
  padding: 0 1rem 0.75rem;
  display: grid;
  gap: 0.35rem;
}

.body p {
  margin: 0;
  font-size: 0.86rem;
  color: var(--ink);
  line-height: 1.45;
}

.label {
  display: inline-block;
  min-width: 2.6rem;
  margin-right: 0.45rem;
  color: var(--muted);
  font-size: 0.8rem;
}

.empty {
  color: var(--muted);
}

.clear {
  margin-top: 0.35rem;
  justify-self: start;
  border: 1px solid var(--line);
  background: var(--bg);
  color: var(--ink-soft);
  border-radius: 999px;
  padding: 0.32rem 0.75rem;
  font-size: 0.78rem;
  cursor: pointer;
}

.clear:hover:not(:disabled) {
  background: var(--bg-soft);
}

.clear:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
