<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { logout as apiLogout } from '../api/auth'
import { ApiError, postChat } from '../api/chat'
import {
  clearSessionContext,
  deleteSession as apiDeleteSession,
  getSessionContext,
  getSessionMessages,
  listSessions,
} from '../api/sessions'
import ChatComposer from '../components/ChatComposer.vue'
import ChatMessage from '../components/ChatMessage.vue'
import ChatSidebar from '../components/ChatSidebar.vue'
import ContextPanel from '../components/ContextPanel.vue'
import { clearAuth, useAuth } from '../stores/auth'
import type {
  ChatMessageItem,
  PublicContext,
  SessionMessage,
  SessionSummary,
  ThinkingState,
} from '../types/recipe'

const route = useRoute()
const router = useRouter()
const { user } = useAuth()

const messages = ref<ChatMessageItem[]>([])
const sessionId = ref<string | null>(null)
const sessionTitle = ref('新对话')
const sessions = ref<SessionSummary[]>([])
const sessionsLoading = ref(false)
const sidebarOpen = ref(false)
const draft = ref('')
const retryDraft = ref('')
const busy = ref(false)
const sessionContext = ref<PublicContext | null>(null)
const listRef = ref<HTMLElement | null>(null)
let abortController: AbortController | null = null
let historyController: AbortController | null = null

const isFresh = computed(() => messages.value.length === 0)
const showRetry = computed(
  () => messages.value.some((m) => m.role === 'error') && !!retryDraft.value,
)
const headerTitle = computed(() => (isFresh.value ? '新对话' : sessionTitle.value))
const routeSessionId = computed(() => {
  const raw = route.params.sessionId
  return typeof raw === 'string' && raw.length > 0 ? raw : null
})

const suggestions = [
  '我有鸡蛋、番茄和葱，想做 20 分钟晚饭',
  '四菜一汤：排骨、土豆、豆角、鸡蛋、番茄',
  '只有鸡胸肉和西兰花，少油健康一点',
]

function resetLocalChat() {
  historyController?.abort()
  sessionId.value = null
  sessionTitle.value = '新对话'
  messages.value = []
  sessionContext.value = null
  draft.value = ''
  retryDraft.value = ''
  sidebarOpen.value = false
}

function mapHistoryMessages(
  rows: SessionMessage[],
  contextStartMessageId: number | null | undefined,
): ChatMessageItem[] {
  const items: ChatMessageItem[] = []
  let dividerInserted = false
  for (const m of rows) {
    if (
      contextStartMessageId != null &&
      !dividerInserted &&
      m.id > contextStartMessageId
    ) {
      // Insert divider just before the first message after the clear boundary.
      // Prefer placing it after the last message at/before the boundary.
      items.push({
        id: `divider-${contextStartMessageId}`,
        role: 'divider',
        text: '已重新开始，之前的聊天不再作为本次参考',
      })
      dividerInserted = true
    }
    if (m.role === 'user') {
      items.push({ id: String(m.id), role: 'user', text: m.content })
      continue
    }
    const thinking = historyThinking(m.thinking)
    if (m.recipe) {
      items.push({
        id: String(m.id),
        role: 'assistant',
        recipe: m.recipe,
        thinking,
      })
    } else {
      items.push({
        id: String(m.id),
        role: 'assistant',
        text: m.content,
        thinking,
      })
    }
  }
  // Cleared with no newer messages yet: still show divider at end if boundary set.
  if (
    contextStartMessageId != null &&
    !dividerInserted &&
    rows.length > 0 &&
    rows[rows.length - 1].id <= contextStartMessageId
  ) {
    items.push({
      id: `divider-${contextStartMessageId}`,
      role: 'divider',
      text: '已重新开始，之前的聊天不再作为本次参考',
    })
  }
  return items
}

async function syncRouteSession(id: string | null) {
  if (!id) {
    if (sessionId.value !== null || messages.value.length > 0) {
      resetLocalChat()
    }
    return
  }

  // Already showing this thread (e.g. URL updated after first reply).
  if (id === sessionId.value && messages.value.length > 0) {
    return
  }

  historyController?.abort()
  historyController = new AbortController()
  const signal = historyController.signal

  try {
    const [data, ctx] = await Promise.all([
      getSessionMessages(id, signal),
      getSessionContext(id, signal).catch(() => null),
    ])
    if (signal.aborted) return
    sessionId.value = data.session_id
    sessionTitle.value = data.title
    sessionContext.value = ctx
    messages.value = mapHistoryMessages(
      data.messages,
      ctx?.context_start_message_id ?? null,
    )
    draft.value = ''
    retryDraft.value = ''
    sidebarOpen.value = false
    await scrollToBottom()
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') return
    await router.replace({ name: 'chat' })
  }
}

watch(
  routeSessionId,
  (id) => {
    void syncRouteSession(id)
  },
  { immediate: true },
)

onMounted(() => {
  void refreshSessions()
})

async function scrollToBottom() {
  await nextTick()
  listRef.value?.scrollTo({ top: listRef.value.scrollHeight, behavior: 'smooth' })
}

function uid() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function updateStatusThinking(statusId: string, content: string) {
  const item = messages.value.find((m) => m.id === statusId)
  if (!item) return
  item.thinking = {
    content,
    running: true,
    defaultOpen: true,
  }
}

function finishedThinking(content: string | null | undefined, elapsedMs: number): ThinkingState | undefined {
  const text = content?.trim()
  if (!text) return undefined
  return {
    content: text,
    running: false,
    elapsedMs,
    defaultOpen: true,
  }
}

function historyThinking(content: string | null | undefined): ThinkingState | undefined {
  const text = content?.trim()
  if (!text) return undefined
  return {
    content: text,
    running: false,
    defaultOpen: false,
  }
}

async function refreshSessions() {
  sessionsLoading.value = true
  try {
    sessions.value = await listSessions()
  } catch {
    // Sidebar can stay empty; chat still works.
  } finally {
    sessionsLoading.value = false
  }
}

function titleFromMessage(message: string) {
  const text = message.trim().replace(/\s+/g, ' ')
  if (!text) return '新对话'
  return text.length <= 36 ? text : `${text.slice(0, 35).trimEnd()}…`
}

function upsertSessionLocal(id: string, title: string) {
  const now = new Date().toISOString()
  const existing = sessions.value.find((s) => s.id === id)
  if (existing) {
    existing.title = title
    existing.last_active_at = now
    sessions.value = [existing, ...sessions.value.filter((s) => s.id !== id)]
    return
  }
  sessions.value = [
    {
      id,
      title,
      created_at: now,
      last_active_at: now,
    },
    ...sessions.value,
  ]
}

async function handleSubmit(payload: { message: string }) {
  if (busy.value) return

  busy.value = true
  retryDraft.value = payload.message
  draft.value = ''

  const isNewThread = !sessionId.value
  if (isNewThread) {
    sessionTitle.value = titleFromMessage(payload.message)
  }

  messages.value.push({ id: uid(), role: 'user', text: payload.message })
  const statusId = uid()
  const startedAt = Date.now()
  messages.value.push({
    id: statusId,
    role: 'status',
    text: '思考中',
    phase: 'parsing',
    thinking: {
      content: '开始分析本轮意图与做饭条件…',
      running: true,
      defaultOpen: true,
    },
  })
  await scrollToBottom()

  abortController?.abort()
  abortController = new AbortController()

  try {
    const response = await postChat({
      message: payload.message,
      sessionId: sessionId.value,
      signal: abortController.signal,
      onThinking: (content) => {
        updateStatusThinking(statusId, content)
        void scrollToBottom()
      },
    })

    sessionId.value = response.session_id
    if (response.context) {
      sessionContext.value = response.context
    }
    upsertSessionLocal(response.session_id, sessionTitle.value)
    if (isNewThread || routeSessionId.value !== response.session_id) {
      await router.replace({
        name: 'chat-session',
        params: { sessionId: response.session_id },
      })
    }

    const liveThinking = messages.value.find((m) => m.id === statusId)?.thinking?.content
    const thinking = finishedThinking(
      response.thinking || liveThinking,
      response.meta.elapsed_ms || Date.now() - startedAt,
    )
    messages.value = messages.value.filter((m) => m.id !== statusId)

    if (response.status === 'completed' && response.recipe) {
      messages.value.push({
        id: uid(),
        role: 'assistant',
        recipe: response.recipe,
        thinking,
      })
      retryDraft.value = ''
    } else if (
      response.status === 'clarification' ||
      response.status === 'insufficient_sources' ||
      (response.status === 'completed' && !response.recipe)
    ) {
      // clarification / explain / insufficient: plain assistant text, no retry button
      messages.value.push({
        id: uid(),
        role: 'assistant',
        text:
          response.message ||
          (response.status === 'insufficient_sources'
            ? '没有足够的真实来源来整理菜谱，请换一组食材或放宽条件。'
            : '好的。'),
        thinking,
      })
      retryDraft.value = ''
    } else {
      messages.value.push({
        id: uid(),
        role: 'error',
        text: response.message || '出错了，请稍后重试。',
        thinking,
      })
      draft.value = retryDraft.value
    }

    void refreshSessions()
  } catch (err) {
    messages.value = messages.value.filter((m) => m.id !== statusId)
    if (err instanceof ApiError && (err.code === 'SESSION_BUSY' || err.status === 409)) {
      messages.value.push({
        id: uid(),
        role: 'error',
        text: '此对话正在生成，请稍后再试',
      })
      draft.value = retryDraft.value
    } else {
      const text =
        err instanceof ApiError
          ? err.message
          : err instanceof DOMException && err.name === 'AbortError'
            ? '请求已取消'
            : '网络异常，请检查连接后重试。输入内容已为你保留。'
      messages.value.push({ id: uid(), role: 'error', text })
      draft.value = retryDraft.value
    }
  } finally {
    busy.value = false
    await scrollToBottom()
  }
}

function retryLast() {
  const message = (draft.value || retryDraft.value).trim()
  if (!message || busy.value) return
  void handleSubmit({ message })
}

async function handleClearContext() {
  if (!sessionId.value || busy.value) return
  try {
    const ctx = await clearSessionContext(sessionId.value)
    sessionContext.value = ctx
    messages.value.push({
      id: `divider-${ctx.context_start_message_id ?? Date.now()}`,
      role: 'divider',
      text: '已重新开始，之前的聊天不再作为本次参考',
    })
    await scrollToBottom()
  } catch (err) {
    const text =
      err instanceof ApiError ? err.message : '清除上下文失败，请稍后重试。'
    messages.value.push({ id: uid(), role: 'error', text })
  }
}

function useSuggestion(text: string) {
  draft.value = text
}

function startNewChat() {
  if (busy.value) {
    abortController?.abort()
  }
  if (route.name === 'chat' && !routeSessionId.value) {
    resetLocalChat()
    return
  }
  void router.push({ name: 'chat' })
}

function selectSession(id: string) {
  if (busy.value || id === routeSessionId.value) return
  void router.push({ name: 'chat-session', params: { sessionId: id } })
}

async function removeSession(id: string) {
  try {
    await apiDeleteSession(id)
    sessions.value = sessions.value.filter((s) => s.id !== id)
    if (sessionId.value === id || routeSessionId.value === id) {
      startNewChat()
    }
  } catch {
    // Ignore; user can retry.
  }
}

async function handleLogout() {
  try {
    await apiLogout()
  } catch {
    // Local clear still proceeds even if the network call fails.
  }
  clearAuth()
  sessionId.value = null
  sessionContext.value = null
  messages.value = []
  sessions.value = []
  await router.replace('/login')
}
</script>

<template>
  <div class="app">
    <ChatSidebar
      :sessions="sessions"
      :active-session-id="sessionId"
      :username="user?.username || '用户'"
      :open="sidebarOpen"
      :loading="sessionsLoading"
      @update:open="(v) => (sidebarOpen = v)"
      @new-chat="startNewChat"
      @select="selectSession"
      @delete="removeSession"
      @logout="handleLogout"
      @preferences="() => router.push({ name: 'preferences' })"
    />

    <div v-if="sidebarOpen" class="scrim" @click="sidebarOpen = false" />

    <div class="stage">
      <header class="topbar">
        <button
          type="button"
          class="menu-btn"
          aria-label="打开对话历史"
          @click="sidebarOpen = true"
        >
          <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
            <path fill="currentColor" d="M3 6h18v2H3zm0 5h18v2H3zm0 5h18v2H3z" />
          </svg>
        </button>
        <h1 class="thread-title">{{ headerTitle }}</h1>
        <button type="button" class="new-btn" aria-label="开启新对话" @click="startNewChat">
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
            <path fill="currentColor" d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6z" />
          </svg>
        </button>
      </header>

      <ContextPanel
        v-if="!isFresh"
        :context="sessionContext"
        :busy="busy"
        @clear="handleClearContext"
      />

      <main ref="listRef" class="thread" :class="{ fresh: isFresh }" aria-live="polite">
        <div class="thread-inner">
          <div v-if="isFresh" class="empty">
            <h2>今天想做什么菜？</h2>
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
        </div>
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
  height: 100dvh;
  max-height: 100dvh;
  overflow: hidden;
  display: flex;
  background: var(--bg);
}

.scrim {
  display: none;
}

.stage {
  flex: 1;
  min-width: 0;
  min-height: 0;
  height: 100%;
  overflow: hidden;
  display: grid;
  grid-template-rows: 52px auto minmax(0, 1fr) auto;
}

.topbar {
  display: grid;
  grid-template-columns: 2.4rem 1fr 2.4rem;
  align-items: center;
  gap: 0.35rem;
  padding: 0 0.85rem;
  border-bottom: 1px solid transparent;
}

.menu-btn,
.new-btn {
  width: 2.2rem;
  height: 2.2rem;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: var(--ink-soft);
  display: none;
  place-items: center;
  cursor: pointer;
}

.menu-btn:hover,
.new-btn:hover {
  background: var(--bg-soft);
}

.thread-title {
  margin: 0;
  text-align: center;
  font-size: 0.95rem;
  font-weight: 560;
  color: var(--ink-soft);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.thread {
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  padding: 0.5rem 1rem 1.25rem;
  scroll-behavior: smooth;
  overscroll-behavior: contain;
}

.thread.fresh {
  display: grid;
  align-content: center;
}

.thread-inner {
  width: min(100%, var(--content-width));
  margin: 0 auto;
}

.empty {
  margin: 0 0 2.5rem;
  text-align: center;
  animation: fade 420ms var(--ease) both;
}

.empty h2 {
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
  flex-shrink: 0;
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

@media (max-width: 860px) {
  .scrim {
    display: block;
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.28);
    z-index: 25;
  }

  .menu-btn,
  .new-btn {
    display: grid;
  }

  .topbar {
    border-bottom-color: var(--line);
  }
}

@media (min-width: 861px) {
  .topbar {
    grid-template-columns: 1fr;
  }

  .thread-title {
    font-size: 1rem;
    color: var(--ink);
  }
}
</style>
