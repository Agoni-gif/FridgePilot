<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  ApiError,
  deleteMyPreferences,
  getMyPreferences,
  patchMyPreferences,
} from '../api/preferences'
import type { PreferenceValues, UserPreferencesResponse } from '../types/preferences'

const router = useRouter()

const loading = ref(true)
const saving = ref(false)
const error = ref('')
const notice = ref('')
const version = ref(0)
const enabled = ref(false)
const servings = ref<number | null>(null)
const maxTime = ref<number | null>(null)
const cuisine = ref('')
const dietaryText = ref('')
const allergiesText = ref('')

/** Server snapshot shown during a version conflict; form keeps the local draft. */
const conflictServer = ref<UserPreferencesResponse | null>(null)

const canSave = computed(() => !loading.value && !saving.value)
const hasConflict = computed(() => conflictServer.value !== null)

function splitList(raw: string): string[] {
  return raw
    .split(/[,，、\n]/)
    .map((s) => s.trim())
    .filter(Boolean)
    .slice(0, 10)
}

function applyResponse(data: UserPreferencesResponse) {
  version.value = data.version
  enabled.value = data.enabled
  servings.value = data.preferences.servings
  maxTime.value = data.preferences.max_time_minutes
  cuisine.value = data.preferences.cuisine || ''
  dietaryText.value = (data.preferences.dietary_restrictions || []).join('、')
  allergiesText.value = (data.preferences.allergies || []).join('、')
}

function draftSet(): Partial<PreferenceValues> {
  return {
    servings: Number.isFinite(servings.value as number) ? servings.value : null,
    max_time_minutes: Number.isFinite(maxTime.value as number) ? maxTime.value : null,
    cuisine: cuisine.value.trim() || null,
    dietary_restrictions: splitList(dietaryText.value),
    allergies: splitList(allergiesText.value),
  }
}

async function load() {
  loading.value = true
  error.value = ''
  conflictServer.value = null
  try {
    applyResponse(await getMyPreferences())
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : '加载偏好失败'
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!canSave.value) return
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    const data = await patchMyPreferences({
      version: version.value,
      enabled: enabled.value,
      set: draftSet(),
      clear: [],
    })
    conflictServer.value = null
    applyResponse(data)
    notice.value = '已保存。启用后将用于后续对话；本次聊天仍可临时调整普通口味。'
  } catch (err) {
    if (err instanceof ApiError && err.status === 409) {
      // Keep the local draft; fetch latest server values for comparison only.
      try {
        const latest = await getMyPreferences()
        conflictServer.value = latest
        version.value = latest.version
        error.value =
          '偏好已被其他设备修改。当前表单仍保留你的未保存编辑；可加载服务器最新值，或基于最新版本再次保存。'
      } catch {
        conflictServer.value = null
        error.value =
          '偏好已被其他设备修改，且无法读取最新值。请稍后刷新页面后再试。'
      }
    } else {
      error.value = err instanceof ApiError ? err.message : '保存失败'
    }
  } finally {
    saving.value = false
  }
}

function loadServerValues() {
  if (!conflictServer.value) return
  applyResponse(conflictServer.value)
  conflictServer.value = null
  error.value = ''
  notice.value = '已加载服务器最新偏好，可继续编辑后保存。'
}

function dismissConflict() {
  conflictServer.value = null
  error.value = ''
}

async function clearAll() {
  if (!canSave.value) return
  const ok = window.confirm('删除全部长期做饭偏好？删除后不会从旧聊天自动恢复。')
  if (!ok) return
  saving.value = true
  error.value = ''
  notice.value = ''
  conflictServer.value = null
  try {
    applyResponse(await deleteMyPreferences())
    notice.value = '已删除长期偏好。'
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : '删除失败'
  } finally {
    saving.value = false
  }
}

function goBack() {
  void router.push({ name: 'chat' })
}

function formatServerPreview(data: UserPreferencesResponse): string {
  const p = data.preferences
  const parts: string[] = [
    data.enabled ? '已启用' : '未启用',
    `版本 ${data.version}`,
  ]
  if (p.servings != null) parts.push(`人数 ${p.servings}`)
  if (p.max_time_minutes != null) parts.push(`${p.max_time_minutes} 分钟`)
  if (p.cuisine) parts.push(p.cuisine)
  if (p.dietary_restrictions?.length) parts.push(p.dietary_restrictions.join('、'))
  if (p.allergies?.length) parts.push(`过敏：${p.allergies.join('、')}`)
  return parts.join(' · ')
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="page">
    <header class="top">
      <button type="button" class="back" @click="goBack">返回对话</button>
      <h1>我的做饭偏好</h1>
    </header>

    <main class="body">
      <p class="lead">
        用于后续对话的默认条件。本次聊天可以临时调整普通口味要求；过敏声明是硬约束，冲突时需移除相关食材或先在此修改声明。
      </p>

      <p v-if="loading" class="muted">加载中…</p>
      <p v-else-if="error" class="err">{{ error }}</p>
      <p v-else-if="notice" class="ok">{{ notice }}</p>

      <div v-if="hasConflict && conflictServer" class="conflict">
        <p class="conflict-title">版本冲突</p>
        <p class="conflict-preview">服务器最新：{{ formatServerPreview(conflictServer) }}</p>
        <div class="conflict-actions">
          <button type="button" class="ghost" :disabled="saving" @click="loadServerValues">
            加载最新值
          </button>
          <button type="button" class="primary" :disabled="!canSave" @click="save">
            用草稿覆盖保存
          </button>
          <button type="button" class="ghost" :disabled="saving" @click="dismissConflict">
            继续编辑草稿
          </button>
        </div>
      </div>

      <form v-if="!loading" class="form" @submit.prevent="save">
        <label class="switch-row">
          <span>启用长期偏好</span>
          <input v-model="enabled" type="checkbox" />
        </label>
        <p class="hint">默认关闭。开启后，未在当前会话明确设置的字段会使用下列默认值。</p>

        <label>
          常用人数
          <input
            v-model.number="servings"
            type="number"
            min="1"
            max="20"
            placeholder="例如 2"
          />
        </label>

        <label>
          常用时间上限（分钟）
          <input
            v-model.number="maxTime"
            type="number"
            min="1"
            max="300"
            placeholder="例如 30"
          />
        </label>

        <label>
          偏好菜系
          <input v-model="cuisine" type="text" maxlength="50" placeholder="例如 家常 / 粤菜" />
        </label>

        <label>
          饮食限制（普通口味）
          <textarea
            v-model="dietaryText"
            rows="2"
            maxlength="200"
            placeholder="用顿号或逗号分隔，例如：不辣、少油"
          />
        </label>

        <label>
          过敏声明（单独管理）
          <textarea
            v-model="allergiesText"
            rows="2"
            maxlength="200"
            placeholder="例如：花生、香菜。对话中不能临时破例"          />
        </label>

        <div class="actions">
          <button type="submit" class="primary" :disabled="!canSave">
            {{ saving ? '保存中…' : '保存' }}
          </button>
          <button type="button" class="ghost" :disabled="!canSave" @click="clearAll">
            清空并删除
          </button>
        </div>
      </form>
    </main>
  </div>
</template>

<style scoped>
.page {
  min-height: 100dvh;
  background:
    radial-gradient(1200px 500px at 10% -10%, rgba(46, 125, 50, 0.08), transparent 60%),
    var(--bg);
  color: var(--ink);
}

.top {
  display: flex;
  align-items: center;
  gap: 0.85rem;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--line);
}

.top h1 {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 650;
}

.back {
  border: 1px solid var(--line);
  background: var(--bg);
  border-radius: 999px;
  padding: 0.35rem 0.8rem;
  color: var(--ink-soft);
  cursor: pointer;
}

.body {
  width: min(100%, 34rem);
  margin: 0 auto;
  padding: 1.25rem 1.1rem 2.5rem;
}

.lead,
.hint,
.muted {
  color: var(--muted);
  line-height: 1.55;
  font-size: 0.92rem;
}

.err {
  color: var(--danger);
}

.ok {
  color: var(--brand);
}

.conflict {
  margin-top: 0.85rem;
  padding: 0.85rem 0.95rem;
  border: 1px solid color-mix(in srgb, var(--danger) 35%, var(--line));
  border-radius: 14px;
  background: color-mix(in srgb, var(--danger) 6%, var(--bg));
  display: grid;
  gap: 0.55rem;
}

.conflict-title {
  margin: 0;
  font-weight: 600;
  color: var(--danger);
}

.conflict-preview {
  margin: 0;
  font-size: 0.88rem;
  color: var(--ink-soft);
  line-height: 1.45;
}

.conflict-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.form {
  display: grid;
  gap: 0.95rem;
  margin-top: 1rem;
}

label {
  display: grid;
  gap: 0.35rem;
  font-size: 0.9rem;
  color: var(--ink-soft);
}

.switch-row {
  grid-template-columns: 1fr auto;
  align-items: center;
  font-weight: 560;
  color: var(--ink);
}

input,
textarea {
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 0.65rem 0.75rem;
  background: var(--bg);
  color: var(--ink);
  font: inherit;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
  margin-top: 0.4rem;
}

.primary,
.ghost {
  border-radius: 999px;
  padding: 0.55rem 1.1rem;
  font: inherit;
  cursor: pointer;
}

.primary {
  border: 0;
  background: var(--brand);
  color: #fff;
}

.primary:disabled,
.ghost:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.ghost {
  border: 1px solid var(--line);
  background: var(--bg);
  color: var(--ink-soft);
}
</style>
