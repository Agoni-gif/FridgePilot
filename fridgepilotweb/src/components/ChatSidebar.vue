<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import type { SessionSummary } from '../types/recipe'

const props = defineProps<{
  sessions: SessionSummary[]
  activeSessionId: string | null
  username: string
  open: boolean
  loading?: boolean
}>()

const emit = defineEmits<{
  'new-chat': []
  select: [sessionId: string]
  delete: [sessionId: string]
  // 以下为「更多」菜单预留的事件，父组件暂未接入，点击只做占位（关闭菜单）
  rename: [sessionId: string]
  pin: [sessionId: string]
  share: [sessionId: string]
  'multi-select': [sessionId: string]
  logout: []
  preferences: []
  'update:open': [value: boolean]
}>()

const query = ref('')
const searchOpen = ref(false)
const searchRef = ref<HTMLInputElement | null>(null)
const menuSessionId = ref<string | null>(null)
const menuPos = ref<{ top: number; left: number } | null>(null)

type MenuKey = 'rename' | 'pin' | 'share' | 'multi-select' | 'delete'

// 菜单尺寸用于点击位置计算：宽度与 .fp-menu 一致，高度为 5*38 + 分隔线 + 内边距
const MENU_WIDTH = 132
const MENU_HEIGHT = 212
const MENU_GAP = 6
const MENU_EDGE = 8

const menuItems: { key: MenuKey; label: string; danger?: boolean }[] = [
  { key: 'rename', label: '重命名' },
  { key: 'pin', label: '置顶' },
  { key: 'share', label: '分享' },
  { key: 'multi-select', label: '多选' },
  { key: 'delete', label: '删除', danger: true },
]

// 项目未引入图标库，沿用内联 SVG；线性图标与 DeepSeek 菜单保持一致
const menuIcons: Record<MenuKey, string[]> = {
  rename: ['M16.5 3.5a2.12 2.12 0 0 1 3 3L7.5 18.5 3 20l1.5-4.5L16.5 3.5Z'],
  pin: ['M12 2.8 20.2 11 12 19.2 3.8 11 12 2.8Z', 'M12 11v9'],
  share: ['M4 14.5c.4-5.4 3.9-8.8 9.3-8.8H20', 'M16 2.2 20 5.7 16 9.2'],
  'multi-select': [
    'M8 6h13',
    'M8 12h13',
    'M8 18h13',
    'M3.5 6h.01',
    'M3.5 12h.01',
    'M3.5 18h.01',
  ],
  delete: [
    'M3 6h18',
    'M8 6V4.5A1.5 1.5 0 0 1 9.5 3h5A1.5 1.5 0 0 1 16 4.5V6',
    'M18.5 6l-1 13.2a2 2 0 0 1-2 1.8h-7a2 2 0 0 1-2-1.8L5.5 6',
    'M10 10.5v6',
    'M14 10.5v6',
  ],
}

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return props.sessions
  return props.sessions.filter((s) => s.title.toLowerCase().includes(q))
})

type HistoryGroup = { label: string; items: SessionSummary[] }

const groups = computed<HistoryGroup[]>(() => {
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const startOfYesterday = new Date(startOfToday)
  startOfYesterday.setDate(startOfYesterday.getDate() - 1)
  const startOf7 = new Date(startOfToday)
  startOf7.setDate(startOf7.getDate() - 7)
  const startOf30 = new Date(startOfToday)
  startOf30.setDate(startOf30.getDate() - 30)

  const buckets: Record<string, SessionSummary[]> = {
    今天: [],
    昨天: [],
    '7 天内': [],
    '30 天内': [],
    更早: [],
  }

  for (const item of filtered.value) {
    const t = new Date(item.last_active_at)
    if (Number.isNaN(t.getTime()) || t >= startOfToday) buckets['今天'].push(item)
    else if (t >= startOfYesterday) buckets['昨天'].push(item)
    else if (t >= startOf7) buckets['7 天内'].push(item)
    else if (t >= startOf30) buckets['30 天内'].push(item)
    else buckets['更早'].push(item)
  }

  return Object.entries(buckets)
    .filter(([, items]) => items.length > 0)
    .map(([label, items]) => ({ label, items }))
})

async function openSearch() {
  searchOpen.value = true
  await nextTick()
  searchRef.value?.focus()
}

function closeSearch() {
  searchOpen.value = false
  query.value = ''
}

function closeMenu() {
  menuSessionId.value = null
  menuPos.value = null
}

function toggleMenu(sessionId: string, event: MouseEvent) {
  event.preventDefault()
  event.stopPropagation()
  if (menuSessionId.value === sessionId) {
    closeMenu()
    return
  }
  const btn = event.currentTarget as HTMLElement
  const rect = btn.getBoundingClientRect()

  // 从侧栏右缘向右展开，菜单浮在内容区上，不遮挡历史对话列表
  const sidebarRight = btn.closest('.sidebar')?.getBoundingClientRect().right ?? rect.right
  const left = Math.max(
    MENU_EDGE,
    Math.min(sidebarRight + MENU_GAP, window.innerWidth - MENU_WIDTH - MENU_EDGE),
  )
  // 下方空间不足时向上翻转
  const spaceBelow = window.innerHeight - rect.bottom - MENU_GAP - MENU_EDGE
  const spaceAbove = rect.top - MENU_GAP - MENU_EDGE
  const top =
    spaceBelow >= MENU_HEIGHT || spaceBelow >= spaceAbove
      ? rect.bottom + MENU_GAP
      : Math.max(MENU_EDGE, rect.top - MENU_GAP - MENU_HEIGHT)

  menuSessionId.value = sessionId
  menuPos.value = { top, left }
}

function onMenuAction(key: MenuKey) {
  const id = menuSessionId.value
  closeMenu()
  if (!id) return

  // 删除沿用已有能力；其余项仅发出占位事件，功能待后续接入
  switch (key) {
    case 'delete':
      emit('delete', id)
      break
    case 'rename':
      emit('rename', id)
      break
    case 'pin':
      emit('pin', id)
      break
    case 'share':
      emit('share', id)
      break
    case 'multi-select':
      emit('multi-select', id)
      break
  }
}

function onDocClick() {
  closeMenu()
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') closeMenu()
}

onMounted(() => {
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onKeydown)
  // capture 才能捕获 history 容器内部的滚动
  window.addEventListener('scroll', closeMenu, true)
  window.addEventListener('resize', closeMenu)
})
onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onKeydown)
  window.removeEventListener('scroll', closeMenu, true)
  window.removeEventListener('resize', closeMenu)
})

watch(
  () => props.open,
  (open) => {
    if (!open) {
      closeMenu()
      closeSearch()
    }
  },
)
</script>

<template>
  <aside class="sidebar" :class="{ open }">
    <div class="side-head">
      <div class="brand-row">
        <button type="button" class="brand" @click="emit('new-chat')">
          <img class="logo" src="/logo-mark.svg" alt="" width="28" height="28" />
          <span class="name">FridgePilot</span>
        </button>
        <div class="head-actions">
          <button
            type="button"
            class="icon-btn"
            aria-label="搜索对话"
            title="搜索对话"
            @click="openSearch"
          >
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path
                fill="currentColor"
                d="M15.5 14h-.79l-.28-.27A6.47 6.47 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14"
              />
            </svg>
          </button>
          <button
            type="button"
            class="icon-btn close-mobile"
            aria-label="关闭侧栏"
            @click="emit('update:open', false)"
          >
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path
                fill="currentColor"
                d="M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"
              />
            </svg>
          </button>
        </div>
      </div>

      <div v-if="searchOpen" class="search-box">
        <input
          ref="searchRef"
          v-model="query"
          type="search"
          placeholder="搜索对话…"
          @keydown.escape="closeSearch"
        />
        <button type="button" class="text-btn" @click="closeSearch">取消</button>
      </div>

      <button type="button" class="new-chat" @click="emit('new-chat')">
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
          <path fill="currentColor" d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6z" />
        </svg>
        开启新对话
      </button>
    </div>

    <nav class="history" aria-label="对话历史">
      <p v-if="loading" class="empty-hint">加载中…</p>
      <p v-else-if="groups.length === 0" class="empty-hint">
        {{ query.trim() ? '没有匹配的对话' : '还没有对话，发一条消息开始吧' }}
      </p>
      <section v-for="group in groups" :key="group.label" class="group">
        <h2>{{ group.label }}</h2>
        <ul>
          <li v-for="item in group.items" :key="item.id">
            <div class="session" :class="{ active: item.id === activeSessionId }">
              <button
                type="button"
                class="session-main"
                @click="emit('select', item.id); emit('update:open', false)"
              >
                <span class="title">{{ item.title }}</span>
              </button>
              <button
                type="button"
                class="more"
                :class="{ 'menu-open': menuSessionId === item.id }"
                aria-label="更多操作"
                aria-haspopup="menu"
                :aria-expanded="menuSessionId === item.id"
                @click="toggleMenu(item.id, $event)"
              >
                <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true">
                  <circle cx="5" cy="12" r="1.6" />
                  <circle cx="12" cy="12" r="1.6" />
                  <circle cx="19" cy="12" r="1.6" />
                </svg>
              </button>
            </div>
          </li>
        </ul>
      </section>
    </nav>

    <div class="side-foot">
      <div class="account">
        <span class="avatar" aria-hidden="true">{{ username.slice(0, 1).toUpperCase() }}</span>
        <span class="uname">{{ username }}</span>
      </div>
      <div class="foot-actions">
        <button type="button" class="prefs" @click="emit('preferences'); emit('update:open', false)">
          我的做饭偏好
        </button>
        <button type="button" class="logout" @click="emit('logout')">退出</button>
      </div>
    </div>

    <!-- 挂到 body，避免被侧栏 overflow / 移动端 transform 裁剪 -->
    <Teleport to="body">
      <div
        v-if="menuSessionId && menuPos"
        class="fp-menu"
        role="menu"
        :style="{ top: `${menuPos.top}px`, left: `${menuPos.left}px` }"
        @click.stop
      >
        <template v-for="item in menuItems" :key="item.key">
          <div v-if="item.danger" class="fp-menu-divider" role="separator" />
          <button
            type="button"
            class="fp-menu-item"
            :class="{ danger: item.danger }"
            role="menuitem"
            @click="onMenuAction(item.key)"
          >
            <svg
              viewBox="0 0 24 24"
              width="18"
              height="18"
              fill="none"
              stroke="currentColor"
              stroke-width="1.7"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <path v-for="d in menuIcons[item.key]" :key="d" :d="d" />
            </svg>
            <span>{{ item.label }}</span>
          </button>
        </template>
      </div>
    </Teleport>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 268px;
  flex-shrink: 0;
  height: 100%;
  max-height: 100dvh;
  overflow: hidden;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  background: #f9f9f9;
  border-right: 1px solid var(--line);
  position: relative;
  z-index: 30;
}

.side-head {
  padding: 0.85rem 0.75rem 0.55rem;
  display: grid;
  gap: 0.65rem;
}

.brand-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  border: 0;
  background: transparent;
  padding: 0.15rem;
  cursor: pointer;
  color: var(--ink);
  min-width: 0;
}

.logo {
  width: 1.55rem;
  height: 1.55rem;
  border-radius: 50%;
  display: block;
}

.name {
  font-size: 0.98rem;
  font-weight: 650;
  letter-spacing: -0.02em;
}

.head-actions {
  display: inline-flex;
  gap: 0.15rem;
}

.icon-btn {
  width: 2rem;
  height: 2rem;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--ink-soft);
  display: grid;
  place-items: center;
  cursor: pointer;
}

.icon-btn:hover {
  background: rgba(0, 0, 0, 0.05);
}

.close-mobile {
  display: none;
}

.search-box {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 0.4rem;
  align-items: center;
}

.search-box input {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 0.45rem 0.65rem;
  background: #fff;
  color: var(--ink);
}

.search-box input:focus {
  outline: none;
  border-color: color-mix(in srgb, var(--brand) 45%, var(--line));
}

.text-btn {
  border: 0;
  background: transparent;
  color: var(--brand);
  font-size: 0.85rem;
  cursor: pointer;
  padding: 0.25rem 0.2rem;
}

.new-chat {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.35rem;
  width: 100%;
  border: 1px solid var(--line);
  background: #fff;
  color: var(--ink);
  border-radius: 12px;
  padding: 0.55rem 0.75rem;
  font-size: 0.9rem;
  font-weight: 400;
  cursor: pointer;
  transition: background 140ms ease, border-color 140ms ease;
}

.new-chat:hover {
  background: var(--bg-soft);
  border-color: var(--line-strong);
}

.history {
  overflow: auto;
  padding: 0.25rem 0.55rem 0.75rem;
}

.group {
  margin-top: 0.55rem;
}

.group h2 {
  margin: 0;
  padding: 0.45rem 0.55rem 0.25rem;
  font-size: 0.75rem;
  font-weight: 560;
  color: var(--muted);
}

.group ul {
  list-style: none;
  margin: 0;
  padding: 0;
}

.session {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 0.1rem;
  border-radius: 10px;
  color: var(--ink-soft);
  font-size: 0.9rem;
}

.session:hover {
  background: rgba(0, 0, 0, 0.04);
}

.session.active {
  background: color-mix(in srgb, var(--brand) 12%, white);
  color: var(--brand);
}

.session-main {
  min-width: 0;
  border: 0;
  background: transparent;
  text-align: left;
  padding: 0.55rem 0.35rem 0.55rem 0.55rem;
  cursor: pointer;
  color: inherit;
  font: inherit;
}

.title {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* DeepSeek 风格：圆形浅灰底 + 三个小圆点 */
.more {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  opacity: 0;
  border: 0;
  border-radius: 50%;
  background: #edeff2;
  color: #7b8290;
  margin-right: 0.35rem;
  padding: 0;
  cursor: pointer;
  transition: opacity 140ms ease, background 140ms ease, color 140ms ease;
}

.session:hover .more,
.session.active .more,
.more.menu-open,
.more:focus-visible {
  opacity: 1;
}

.more:hover {
  background: #e1e4e9;
  color: var(--ink-soft);
}

/* 触屏设备没有 hover，常显 */
@media (hover: none) {
  .more {
    opacity: 1;
  }
}

.empty-hint {
  margin: 1.5rem 0.75rem;
  color: var(--muted);
  font-size: 0.85rem;
  line-height: 1.5;
}

.side-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.75rem 0.85rem 0.9rem;
  border-top: 1px solid var(--line);
}

.account {
  display: inline-flex;
  align-items: center;
  gap: 0.55rem;
  min-width: 0;
}

.avatar {
  width: 1.7rem;
  height: 1.7rem;
  border-radius: 50%;
  background: color-mix(in srgb, var(--brand) 18%, white);
  color: var(--brand);
  display: grid;
  place-items: center;
  font-size: 0.78rem;
  font-weight: 700;
  flex-shrink: 0;
}

.uname {
  font-size: 0.88rem;
  color: var(--ink-soft);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.foot-actions {
  display: grid;
  gap: 0.35rem;
}

.prefs,
.logout {
  border: 1px solid var(--line);
  background: #fff;
  color: var(--ink-soft);
  border-radius: 999px;
  padding: 0.3rem 0.7rem;
  font-size: 0.8rem;
  cursor: pointer;
  flex-shrink: 0;
}

.prefs:hover,
.logout:hover {
  background: var(--bg-soft);
  border-color: var(--line-strong);
}

@media (max-width: 860px) {
  .sidebar {
    position: fixed;
    left: 0;
    top: 0;
    transform: translateX(-105%);
    transition: transform 220ms var(--ease);
    box-shadow: 12px 0 40px rgba(0, 0, 0, 0.08);
  }

  .sidebar.open {
    transform: translateX(0);
  }

  .close-mobile {
    display: grid;
  }
}
</style>

<!-- 菜单 Teleport 到 body，scoped 样式不作用于它，故单独用带前缀的全局类名 -->
<style>
/* DeepSeek 风格：白色大圆角浮层 + 柔和阴影 */
.fp-menu {
  position: fixed;
  z-index: 200;
  width: 132px;
  padding: 6px;
  background: #fff;
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 14px;
  box-shadow: 0 10px 26px rgba(0, 0, 0, 0.13), 0 2px 6px rgba(0, 0, 0, 0.04);
  animation: fp-menu-in 160ms var(--ease) both;
}

.fp-menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  height: 38px;
  padding: 0 8px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  text-align: left;
  font-size: 0.85rem;
  cursor: pointer;
  color: var(--ink);
  transition: background 120ms ease;
}

.fp-menu-item svg {
  flex-shrink: 0;
}

.fp-menu-item:hover,
.fp-menu-item:focus-visible {
  background: #f4f5f7;
}

.fp-menu-item.danger,
.fp-menu-item.danger:hover {
  color: var(--danger);
}

.fp-menu-divider {
  height: 1px;
  margin: 4px 8px;
  background: var(--line);
}

@keyframes fp-menu-in {
  from {
    opacity: 0;
    transform: translateY(-6px) scale(0.97);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}
</style>
