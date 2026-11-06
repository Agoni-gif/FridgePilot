<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { ApiError, postChat } from '../api/chat'
import ChatComposer from '../components/ChatComposer.vue'
import ChatMessage from '../components/ChatMessage.vue'
import type { ChatMessageItem, ChatPreferences } from '../types/recipe'

const messages = ref<ChatMessageItem[]>([
  {
    id: 'welcome',
    role: 'assistant',
    text: '告诉我冰箱里有什么，以及时间、人数或忌口。我会联网检索真实菜谱，并整理成带来源的步骤。',
  },
])

const sessionId = ref<string | null>(null)
const draft = ref('')
const busy = ref(false)
const listRef = ref<HTMLElement | null>(null)
let abortController: AbortController | null = null

const isFresh = computed(() => messages.value.length <= 1)
const showRetry = computed(() => messages.value.some((m) => m.role === 'error') && !!draft.value)

async function scrollToBottom() {
  await nextTick()
  listRef.value?.scrollTo({ top: listRef.value.scrollHeight, behavior: 'smooth' })
}

function uid() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

async function handleSubmit(payload: { message: string; preferences: ChatPreferences }) {
  if (busy.value) return

  busy.value = true
  draft.value = payload.message

  messages.value.push({ id: uid(), role: 'user', text: payload.message })
  const statusId = uid()
  messages.value.push({
    id: statusId,
    role: 'status',
    text: '正在整理食材…',
    phase: 'parsing',
  })
  await scrollToBottom()

  const phaseTimer = window.setTimeout(() => {
    const item = messages.value.find((m) => m.id === statusId)
    if (item) item.text = '正在搜索菜谱…'
  }, 900)
  const phaseTimer2 = window.setTimeout(() => {
    const item = messages.value.find((m) => m.id === statusId)
    if (item) item.text = '正在生成步骤…'
  }, 2200)

  abortController?.abort()
  abortController = new AbortController()

  try {
    const response = await postChat({
      message: payload.message,
      sessionId: sessionId.value,
      preferences: payload.preferences,
      signal: abortController.signal,
    })

    sessionId.value = response.session_id
    messages.value = messages.value.filter((m) => m.id !== statusId)

    if (response.status === 'completed' && response.recipe) {
      messages.value.push({
        id: uid(),
        role: 'assistant',
        recipe: response.recipe,
      })
      draft.value = ''
    } else if (response.status === 'insufficient_sources') {
      messages.value.push({
        id: uid(),
        role: 'assistant',
        text: response.message || '没有足够的真实来源来整理菜谱，请换一组食材或放宽条件。',
      })
    } else {
      messages.value.push({
        id: uid(),
        role: 'error',
        text: response.message || '出错了，请稍后重试。',
      })
    }
  } catch (err) {
    messages.value = messages.value.filter((m) => m.id !== statusId)
    const text =
      err instanceof ApiError
        ? err.message
        : err instanceof DOMException && err.name === 'AbortError'
          ? '请求已取消'
          : '网络异常，请检查连接后重试。输入内容已为你保留。'
    messages.value.push({ id: uid(), role: 'error', text })
  } finally {
    window.clearTimeout(phaseTimer)
    window.clearTimeout(phaseTimer2)
    busy.value = false
    await scrollToBottom()
  }
}

function retryLast() {
  if (!draft.value.trim() || busy.value) return
  void handleSubmit({
    message: draft.value.trim(),
    preferences: {
      max_time_minutes: 20,
      servings: 2,
      dietary_restrictions: [],
    },
  })
}
</script>

<template>
  <div class="shell" :class="{ fresh: isFresh }">
    <div class="glow" aria-hidden="true" />

    <header class="masthead">
      <div class="brand-block">
        <p class="mark">FridgePilot</p>
        <p class="tagline">把现有食材，变成有来源的烹饪指南</p>
      </div>
      <p class="aside">真实检索 · 可核验来源</p>
    </header>

    <main ref="listRef" class="stream" aria-live="polite">
      <ChatMessage v-for="item in messages" :key="item.id" :item="item" />
    </main>

    <footer class="dock">
      <div v-if="showRetry" class="retry-row">
        <button type="button" class="retry" :disabled="busy" @click="retryLast">
          重试上一次输入
        </button>
      </div>
      <ChatComposer
        :disabled="busy"
        :draft="draft"
        @update:draft="(v) => (draft = v)"
        @submit="handleSubmit"
      />
    </footer>
  </div>
</template>

<style scoped>
.shell {
  position: relative;
  isolation: isolate;
  min-height: 100dvh;
  max-width: 720px;
  margin: 0 auto;
  padding: 1.35rem 1.15rem 1.2rem;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  gap: 1rem;
}

.shell.fresh {
  gap: 1.2rem;
}

.glow {
  position: absolute;
  inset: 8% 12% auto;
  height: 180px;
  background: radial-gradient(ellipse at center, rgba(201, 162, 39, 0.22), transparent 70%);
  filter: blur(18px);
  z-index: -1;
  animation: breathe 5.5s var(--ease) infinite;
  pointer-events: none;
}

.masthead {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 1rem;
  padding-bottom: 0.85rem;
  border-bottom: 1px solid color-mix(in srgb, var(--line) 80%, transparent);
  animation: enter 560ms var(--ease) both;
}

.brand-block {
  min-width: 0;
}

.mark {
  margin: 0;
  font-family: var(--font-display);
  font-weight: 700;
  font-size: clamp(2rem, 6vw, 2.75rem);
  line-height: 1.05;
  letter-spacing: -0.02em;
  color: var(--ink);
}

.shell.fresh .mark {
  font-size: clamp(2.15rem, 7vw, 3rem);
}

.tagline {
  margin: 0.55rem 0 0;
  max-width: 22rem;
  color: var(--ink-soft);
  font-size: 1rem;
  line-height: 1.45;
}

.aside {
  margin: 0 0 0.25rem;
  flex-shrink: 0;
  font-size: 0.78rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
  writing-mode: horizontal-tb;
}

.stream {
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 0.35rem 0.1rem 0.6rem;
  min-height: 12rem;
  scroll-behavior: smooth;
  animation: enter 700ms var(--ease) both;
}

.dock {
  display: grid;
  gap: 0.7rem;
  padding: 0.15rem 0 0.2rem;
  animation: enter 820ms var(--ease) both;
}

.dock::before {
  content: '';
  display: block;
  height: 1px;
  margin: 0 0.2rem 0.15rem;
  background: linear-gradient(
    90deg,
    transparent,
    color-mix(in srgb, var(--line) 90%, var(--ink)),
    transparent
  );
}

.retry-row {
  display: flex;
}

.retry {
  border: 1px solid var(--line);
  background: var(--panel-solid);
  color: var(--ink);
  border-radius: 10px;
  padding: 0.5rem 0.85rem;
  cursor: pointer;
  transition: border-color 160ms ease, background 160ms ease;
}

.retry:hover:not(:disabled) {
  border-color: var(--accent);
  background: var(--accent-wash);
}

.retry:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@keyframes enter {
  from {
    opacity: 0;
    transform: translateY(14px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes breathe {
  0%,
  100% {
    opacity: 0.55;
    transform: scale(0.96);
  }
  50% {
    opacity: 1;
    transform: scale(1.04);
  }
}

@media (max-width: 640px) {
  .masthead {
    flex-direction: column;
    align-items: start;
  }

  .aside {
    margin: 0;
  }
}
</style>
