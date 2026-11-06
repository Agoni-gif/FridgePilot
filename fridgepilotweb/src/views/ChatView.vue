<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useRouter } from 'vue-router'
import { logout as apiLogout } from '../api/auth'
import { ApiError, postChat } from '../api/chat'
import ChatComposer from '../components/ChatComposer.vue'
import ChatMessage from '../components/ChatMessage.vue'
import { clearAuth, useAuth } from '../stores/auth'
import type { ChatMessageItem, ChatPreferences } from '../types/recipe'

const router = useRouter()
const { user } = useAuth()

const messages = ref<ChatMessageItem[]>([])
const sessionId = ref<string | null>(null)
const draft = ref('')
const busy = ref(false)
const listRef = ref<HTMLElement | null>(null)
let abortController: AbortController | null = null

const isFresh = computed(() => messages.value.length === 0)
const showRetry = computed(() => messages.value.some((m) => m.role === 'error') && !!draft.value)

const suggestions = [
  '我有鸡蛋、番茄和葱，想做 20 分钟晚饭',
  '四菜一汤：排骨、土豆、豆角、鸡蛋、番茄',
  '只有鸡胸肉和西兰花，少油健康一点',
]

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
      max_time_minutes: null,
      servings: null,
      dietary_restrictions: [],
    },
  })
}

function useSuggestion(text: string) {
  draft.value = text
}

async function handleLogout() {
  try {
    await apiLogout()
  } catch {
    // Local clear still proceeds even if the network call fails.
  }
  clearAuth()
  sessionId.value = null
  messages.value = []
  await router.replace('/login')
}
</script>

<template>
  <div class="app">
    <header class="topbar">
      <div class="brand">
        <span class="logo" aria-hidden="true">F</span>
        <span class="name">FridgePilot</span>
      </div>
      <div class="account">
        <span class="username">{{ user?.username }}</span>
        <button type="button" class="logout" @click="handleLogout">退出</button>
      </div>
    </header>

    <div class="stage">
      <main ref="listRef" class="thread" :class="{ fresh: isFresh }" aria-live="polite">
        <div v-if="isFresh" class="empty">
          <h1>今天想做什么菜？</h1>
          <p>直接说冰箱里有什么、想做什么，我会联网检索并整理带来源的做法。</p>
          <div class="suggestions">
            <button
              v-for="item in suggestions"
              :key="item"
              type="button"
              class="chip"
              @click="useSuggestion(item)"
            >
              {{ item }}
            </button>
          </div>
        </div>

        <ChatMessage v-for="item in messages" :key="item.id" :item="item" />
      </main>

      <footer class="composer-wrap">
        <div class="composer-inner">
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
          <p class="disclaimer">内容由 AI 整理，步骤与来源请自行核对</p>
        </div>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.app {
  min-height: 100dvh;
  display: grid;
  grid-template-rows: 56px minmax(0, 1fr);
  background: var(--bg);
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0 1.1rem;
  border-bottom: 1px solid transparent;
}

.account {
  display: inline-flex;
  align-items: center;
  gap: 0.65rem;
}

.username {
  font-size: 0.88rem;
  color: var(--ink-soft);
}

.logout {
  border: 1px solid var(--line);
  background: var(--bg);
  color: var(--ink-soft);
  border-radius: 999px;
  padding: 0.35rem 0.75rem;
  font-size: 0.82rem;
  cursor: pointer;
  transition: background 140ms ease, border-color 140ms ease;
}

.logout:hover {
  background: var(--bg-soft);
  border-color: var(--line-strong);
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: 0.55rem;
}

.logo {
  width: 1.7rem;
  height: 1.7rem;
  border-radius: 8px;
  display: grid;
  place-items: center;
  background: var(--brand);
  color: #fff;
  font-size: 0.85rem;
  font-weight: 700;
}

.name {
  font-size: 1rem;
  font-weight: 650;
  letter-spacing: -0.02em;
}

.stage {
  min-height: 0;
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
}

.thread {
  overflow: auto;
  padding: 0.5rem 1rem 1.25rem;
  scroll-behavior: smooth;
}

.thread.fresh {
  display: grid;
  align-content: center;
}

.empty {
  width: min(100%, var(--content-width));
  margin: 0 auto 2.5rem;
  text-align: center;
  animation: fade 420ms var(--ease) both;
}

.empty h1 {
  margin: 0;
  font-size: clamp(1.7rem, 4vw, 2.2rem);
  font-weight: 650;
  letter-spacing: -0.03em;
  line-height: 1.25;
}

.empty p {
  margin: 0.85rem auto 0;
  max-width: 28rem;
  color: var(--muted);
  line-height: 1.6;
  font-size: 0.98rem;
}

.suggestions {
  margin-top: 1.5rem;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 0.55rem;
}

.chip {
  border: 1px solid var(--line);
  background: var(--bg);
  color: var(--ink-soft);
  border-radius: 999px;
  padding: 0.55rem 0.9rem;
  font-size: 0.88rem;
  cursor: pointer;
  transition: background 140ms ease, border-color 140ms ease;
}

.chip:hover {
  background: var(--bg-soft);
  border-color: var(--line-strong);
}

.composer-wrap {
  padding: 0 1rem 0.85rem;
  background: linear-gradient(180deg, transparent, var(--bg) 28%);
}

.composer-inner {
  width: min(100%, var(--content-width));
  margin: 0 auto;
}

.retry-row {
  display: flex;
  justify-content: center;
  margin-bottom: 0.55rem;
}

.retry {
  border: 1px solid var(--line);
  background: var(--bg);
  color: var(--ink-soft);
  border-radius: 999px;
  padding: 0.4rem 0.85rem;
  font-size: 0.85rem;
  cursor: pointer;
}

.retry:hover:not(:disabled) {
  background: var(--bg-soft);
}

.retry:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.disclaimer {
  margin: 0.55rem 0 0;
  text-align: center;
  font-size: 0.75rem;
  color: var(--muted);
}

@keyframes fade {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
