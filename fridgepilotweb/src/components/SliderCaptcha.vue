<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { fetchCaptcha, verifyCaptcha, type CaptchaChallenge } from '../api/auth'
import { ApiError } from '../api/http'

const props = defineProps<{
  resetKey?: number
}>()

const emit = defineEmits<{
  change: [value: { captchaId: string; captchaX: number } | null]
}>()

type ErrorKind = 'none' | 'soft' | 'mismatch' | 'locked' | 'rate' | 'load'

const open = ref(false)
const challenge = ref<CaptchaChallenge | null>(null)
const loading = ref(false)
const verifying = ref(false)
const error = ref('')
const errorKind = ref<ErrorKind>('none')
const dragging = ref(false)
const offsetX = ref(0)
const status = ref<'idle' | 'ok' | 'fail'>('idle')
const panelRef = ref<HTMLElement | null>(null)
let successCloseTimer: ReturnType<typeof setTimeout> | null = null

const blocked = computed(() => errorKind.value === 'locked' || errorKind.value === 'rate')
const showPuzzle = computed(() => !!challenge.value && !blocked.value)

const maxSlide = computed(() => {
  if (!challenge.value) return 0
  return challenge.value.bg_width - challenge.value.piece_size
})

const piecePad = computed(() => challenge.value?.piece_pad ?? 0)

const triggerLabel = computed(() => {
  if (status.value === 'ok') return '验证通过'
  if (verifying.value) return '校验中…'
  if (errorKind.value === 'locked') return '验证暂时不可用'
  return '点击完成安全验证'
})

const trackHint = computed(() => {
  if (status.value === 'ok') return '验证成功'
  if (dragging.value) return '对准缺口后松开'
  if (verifying.value) return '正在校验…'
  return '拖动滑块完成拼图'
})

const emptyTitle = computed(() => {
  if (errorKind.value === 'locked') return '先休息一下'
  if (errorKind.value === 'rate') return '请稍等片刻'
  return '验证码加载失败'
})

const emptyActionLabel = computed(() => {
  if (blocked.value) return '我知道了'
  return '重新加载'
})

function sleep(ms: number) {
  return new Promise<void>((resolve) => {
    setTimeout(resolve, ms)
  })
}

function clearSuccessTimer() {
  if (successCloseTimer) {
    clearTimeout(successCloseTimer)
    successCloseTimer = null
  }
}

function mapError(err: unknown): { kind: ErrorKind; message: string } {
  if (err instanceof ApiError) {
    if (err.code === 'CAPTCHA_LOCKED') {
      return {
        kind: 'locked',
        message: err.message || '尝试次数较多，请稍后再试',
      }
    }
    if (err.code === 'CAPTCHA_RATE_LIMITED') {
      return {
        kind: 'rate',
        message: err.message || '请求有点快，请稍等几秒再试',
      }
    }
    if (err.code === 'CAPTCHA_FAILED') {
      return {
        kind: 'mismatch',
        message: err.message || '位置不太对，已换一题，请再试一次',
      }
    }
    return { kind: 'load', message: err.message || '验证码暂时不可用，请稍后重试' }
  }
  return { kind: 'load', message: '验证码暂时不可用，请稍后重试' }
}

function clearError() {
  error.value = ''
  errorKind.value = 'none'
}

async function load(opts?: { keepFailTip?: boolean }) {
  const tip = opts?.keepFailTip ? error.value || '位置不太对，已换一题，请再试一次' : ''
  const tipKind: ErrorKind = opts?.keepFailTip ? 'mismatch' : 'none'
  loading.value = true
  if (!opts?.keepFailTip) {
    clearError()
    status.value = 'idle'
  }
  offsetX.value = 0
  emit('change', null)
  try {
    challenge.value = await fetchCaptcha()
    if (opts?.keepFailTip) {
      error.value = tip
      errorKind.value = tipKind
      status.value = 'fail'
    } else {
      clearError()
      status.value = 'idle'
    }
  } catch (err) {
    // 限流/锁定：只保留一处友好空态，不再叠第二条红条
    const mapped = mapError(err)
    challenge.value = null
    error.value = mapped.message
    errorKind.value = mapped.kind === 'mismatch' ? 'load' : mapped.kind
    status.value = 'fail'
  } finally {
    loading.value = false
  }
}

async function retryAfterFail() {
  if (loading.value || verifying.value || status.value === 'ok') return
  if (blocked.value) {
    open.value = false
    return
  }
  clearError()
  await load()
}

async function openPanel() {
  if (status.value === 'ok' || verifying.value) return
  open.value = true
  if ((!challenge.value || blocked.value) && !loading.value) {
    await load()
  }
  await nextTick()
  if (showPuzzle.value) {
    panelRef.value?.querySelector<HTMLElement>('.track')?.focus({ preventScroll: true })
  }
}

function closePanel() {
  if (status.value === 'ok' || verifying.value || dragging.value) return
  open.value = false
}

async function onPointerDown(event: PointerEvent) {
  if (!challenge.value || status.value === 'ok' || loading.value || verifying.value || blocked.value) {
    return
  }
  dragging.value = true
  status.value = 'idle'
  clearError()
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
}

function onPointerMove(event: PointerEvent) {
  if (!dragging.value || !challenge.value) return
  const root = (event.currentTarget as HTMLElement).closest('.slider-captcha') as HTMLElement
  const rect = root.querySelector('.track')!.getBoundingClientRect()
  const x = event.clientX - rect.left - 20
  offsetX.value = Math.max(0, Math.min(maxSlide.value, x))
}

async function onPointerUp() {
  if (!dragging.value || !challenge.value) return
  dragging.value = false

  if (offsetX.value < 8) {
    status.value = 'fail'
    offsetX.value = 0
    error.value = '请把滑块拖到拼图缺口处再松开'
    errorKind.value = 'soft'
    emit('change', null)
    return
  }

  verifying.value = true
  const captchaId = challenge.value.captcha_id
  const captchaX = offsetX.value
  try {
    await verifyCaptcha({ captcha_id: captchaId, captcha_x: captchaX })
    status.value = 'ok'
    clearError()
    emit('change', { captchaId, captchaX })
    clearSuccessTimer()
    successCloseTimer = setTimeout(() => {
      open.value = false
      successCloseTimer = null
    }, 700)
  } catch (err) {
    const mapped = mapError(err)
    status.value = 'fail'
    emit('change', null)
    offsetX.value = 0
    error.value = mapped.message
    errorKind.value = mapped.kind
    if (mapped.kind === 'locked' || mapped.kind === 'rate') {
      challenge.value = null
      return
    }
    await sleep(280)
    if (status.value === 'fail' && errorKind.value === 'mismatch') {
      await load({ keepFailTip: true })
    }
  } finally {
    verifying.value = false
  }
}

function onDocPointerDown(event: PointerEvent) {
  if (!open.value || status.value === 'ok') return
  const root = (event.target as Node | null) && (event.target as HTMLElement).closest?.('.slider-captcha')
  if (!root) closePanel()
}

watch(
  () => props.resetKey,
  () => {
    clearSuccessTimer()
    open.value = false
    status.value = 'idle'
    clearError()
    offsetX.value = 0
    emit('change', null)
    challenge.value = null
  },
)

onMounted(() => {
  document.addEventListener('pointerdown', onDocPointerDown)
})

onUnmounted(() => {
  clearSuccessTimer()
  document.removeEventListener('pointerdown', onDocPointerDown)
  emit('change', null)
})

defineExpose({ reload: load })
</script>

<template>
  <div class="slider-captcha" :data-status="status" :data-open="open ? '1' : '0'">
    <button
      type="button"
      class="trigger"
      :disabled="verifying || status === 'ok'"
      :aria-expanded="open"
      aria-haspopup="dialog"
      @click="openPanel"
    >
      <span class="trigger-icon" aria-hidden="true">
        <svg v-if="status === 'ok'" viewBox="0 0 24 24" width="16" height="16">
          <path
            fill="none"
            stroke="currentColor"
            stroke-width="2.6"
            stroke-linecap="round"
            stroke-linejoin="round"
            d="M5 12.5 10 17.5 19 7"
          />
        </svg>
        <svg v-else viewBox="0 0 24 24" width="16" height="16">
          <rect x="4" y="4" width="16" height="16" rx="3" fill="none" stroke="currentColor" stroke-width="1.8" />
          <path
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            d="M8 12h8M12 8v8"
          />
        </svg>
      </span>
      <span>{{ triggerLabel }}</span>
    </button>

    <div
      v-if="open"
      ref="panelRef"
      class="popup"
      role="dialog"
      aria-label="滑块安全验证"
    >
      <div class="panel">
        <div v-if="loading" class="placeholder">验证码加载中…</div>
        <div v-else-if="!showPuzzle" class="empty-state" role="alert">
          <p class="empty-title">{{ emptyTitle }}</p>
          <p class="empty-desc">{{ error || '请稍后重试' }}</p>
          <button type="button" class="empty-action" :disabled="loading" @click="retryAfterFail">
            {{ emptyActionLabel }}
          </button>
        </div>
        <div
          v-else-if="challenge"
          class="stage"
          :style="{ width: challenge.bg_width + 'px', height: challenge.bg_height + 'px' }"
        >
          <img class="bg" :src="challenge.bg_image" alt="" draggable="false" />
          <img
            class="piece"
            :src="challenge.piece_image"
            alt=""
            draggable="false"
            :style="{
              transform: `translate(${offsetX - piecePad}px, ${challenge.piece_y - piecePad}px)`,
            }"
          />
          <button
            v-if="status !== 'ok'"
            type="button"
            class="refresh"
            title="换一张"
            aria-label="换一张"
            @click="load()"
          >
            <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
              <path
                fill="currentColor"
                d="M17.65 6.35A7.95 7.95 0 0 0 12 4V1L7 6l5 5V7c2.76 0 5 2.24 5 5a5 5 0 0 1-8.9 3.1L6.7 16.5A7.97 7.97 0 0 0 20 12c0-2.21-.9-4.21-2.35-5.65z"
              />
            </svg>
          </button>
          <div v-if="status === 'ok'" class="success-overlay" aria-live="polite">
            <span class="success-badge">
              <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
                <path
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2.8"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  d="M5 12.5 10 17.5 19 7"
                />
              </svg>
            </span>
            <span>验证成功</span>
          </div>
        </div>
      </div>

      <template v-if="showPuzzle">
        <div
          v-if="error && status !== 'ok'"
          class="fail-row"
          role="alert"
        >
          <p class="fail-tip">{{ error }}</p>
          <button type="button" class="retry" :disabled="loading || verifying" @click="retryAfterFail">
            <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true">
              <path
                fill="currentColor"
                d="M17.65 6.35A7.95 7.95 0 0 0 12 4V1L7 6l5 5V7c2.76 0 5 2.24 5 5a5 5 0 0 1-8.9 3.1L6.7 16.5A7.97 7.97 0 0 0 20 12c0-2.21-.9-4.21-2.35-5.65z"
              />
            </svg>
            换一张
          </button>
        </div>

        <div
          class="track"
          tabindex="0"
          :data-disabled="verifying || status === 'ok' ? '1' : '0'"
          @pointerdown="onPointerDown"
          @pointermove="onPointerMove"
          @pointerup="onPointerUp"
          @pointercancel="onPointerUp"
        >
          <div class="fill" :style="{ width: offsetX + 40 + 'px' }" />
          <div
            class="knob"
            :style="{ transform: `translateX(${offsetX}px)` }"
            role="slider"
            :aria-valuenow="Math.round(offsetX)"
            :aria-valuemin="0"
            :aria-valuemax="maxSlide"
            :aria-label="trackHint"
          >
            <svg v-if="status === 'ok'" class="knob-svg" viewBox="0 0 24 24" aria-hidden="true">
              <path
                fill="none"
                stroke="currentColor"
                stroke-width="2.6"
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M5 12.5 10 17.5 19 7"
              />
            </svg>
            <svg v-else-if="verifying" class="knob-svg spin" viewBox="0 0 24 24" aria-hidden="true">
              <circle
                cx="12"
                cy="12"
                r="8"
                fill="none"
                stroke="currentColor"
                stroke-width="2.2"
                stroke-dasharray="36 20"
              />
            </svg>
            <svg v-else class="knob-svg" viewBox="0 0 24 24" aria-hidden="true">
              <path
                fill="none"
                stroke="currentColor"
                stroke-width="2.4"
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M8 7h4l4 5-4 5H8l4-5z"
              />
              <path
                fill="none"
                stroke="currentColor"
                stroke-width="2.4"
                stroke-linecap="round"
                d="M5 12h3"
              />
            </svg>
          </div>
          <span class="track-hint" :class="{ hidden: offsetX > 18 || verifying }">{{ trackHint }}</span>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.slider-captcha {
  position: relative;
  width: 100%;
  max-width: 320px;
}

.trigger {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 0.55rem;
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 0.72rem 0.9rem;
  background: var(--bg-soft);
  color: var(--ink-soft);
  font: inherit;
  font-size: 0.9rem;
  cursor: pointer;
  transition:
    border-color 140ms var(--ease),
    background 140ms var(--ease),
    color 140ms var(--ease);
}

.trigger:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--brand) 40%, var(--line));
  color: var(--ink);
}

.trigger:disabled {
  cursor: wait;
  opacity: 0.8;
}

.trigger-icon {
  display: grid;
  place-items: center;
  color: var(--brand);
}

.slider-captcha[data-status='ok'] .trigger {
  border-color: color-mix(in srgb, #1f9d61 40%, var(--line));
  background: color-mix(in srgb, #1f9d61 8%, white);
  color: #1f9d61;
  cursor: default;
  opacity: 0.92;
}

.slider-captcha[data-status='ok'] .trigger-icon {
  color: #1f9d61;
}

.slider-captcha[data-status='ok'] .trigger:disabled {
  opacity: 0.92;
}

.popup {
  position: absolute;
  left: 0;
  right: 0;
  bottom: calc(100% + 0.55rem);
  z-index: 20;
  display: grid;
  gap: 0.65rem;
  padding: 0.65rem;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: var(--bg);
  box-shadow:
    0 10px 28px rgba(15, 23, 42, 0.12),
    0 2px 6px rgba(15, 23, 42, 0.06);
  animation: pop 160ms var(--ease) both;
}

.panel {
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
  background: var(--bg-soft);
}

.stage {
  position: relative;
  margin: 0 auto;
  user-select: none;
  touch-action: none;
  overflow: hidden;
}

.bg,
.piece {
  display: block;
  pointer-events: none;
  user-select: none;
}

.bg {
  width: 100%;
  height: 100%;
}

.piece {
  position: absolute;
  left: 0;
  top: 0;
  will-change: transform;
  filter: drop-shadow(0 4px 8px rgba(15, 23, 42, 0.32));
}

.refresh {
  position: absolute;
  top: 0.5rem;
  right: 0.5rem;
  width: 1.85rem;
  height: 1.85rem;
  border: 0;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.92);
  color: var(--ink-soft);
  cursor: pointer;
  display: grid;
  place-items: center;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.12);
}

.refresh:hover {
  background: #fff;
  color: var(--brand);
}

.placeholder {
  height: 168px;
  display: grid;
  place-items: center;
  gap: 0.4rem;
  color: var(--muted);
  font-size: 0.88rem;
}

.empty-state {
  min-height: 168px;
  display: grid;
  place-content: center;
  justify-items: center;
  gap: 0.45rem;
  padding: 1.2rem 1rem;
  text-align: center;
}

.empty-title {
  margin: 0;
  font-size: 1rem;
  font-weight: 650;
  color: var(--ink);
}

.empty-desc {
  margin: 0;
  max-width: 16rem;
  color: var(--ink-soft);
  font-size: 0.86rem;
  line-height: 1.5;
  text-wrap: pretty;
}

.empty-action {
  margin-top: 0.35rem;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 0.45rem 0.9rem;
  background: #fff;
  color: var(--brand);
  font: inherit;
  font-size: 0.86rem;
  font-weight: 600;
  cursor: pointer;
}

.empty-action:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--brand) 40%, var(--line));
  background: color-mix(in srgb, var(--brand) 6%, white);
}

.empty-action:disabled {
  opacity: 0.6;
  cursor: wait;
}

.fail-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  animation: tip-in 180ms var(--ease) both;
}

.fail-tip {
  margin: 0;
  flex: 1;
  padding: 0.45rem 0.65rem;
  border-radius: 10px;
  background: var(--danger-wash);
  color: var(--danger);
  font-size: 0.82rem;
  line-height: 1.4;
  text-wrap: pretty;
}

.retry {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 0.28rem;
  border: 1px solid color-mix(in srgb, var(--danger) 28%, var(--line));
  border-radius: 10px;
  padding: 0.42rem 0.75rem;
  background: #fff;
  color: var(--danger);
  font: inherit;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
}

.retry:hover:not(:disabled) {
  background: var(--danger-wash);
}

.retry:disabled {
  opacity: 0.6;
  cursor: wait;
}

.success-overlay {
  position: absolute;
  inset: 0;
  display: grid;
  place-content: center;
  justify-items: center;
  gap: 0.45rem;
  background: rgba(15, 23, 42, 0.28);
  color: #fff;
  font-size: 0.95rem;
  font-weight: 650;
  animation: tip-in 180ms var(--ease) both;
}

.success-badge {
  width: 2.6rem;
  height: 2.6rem;
  border-radius: 999px;
  display: grid;
  place-items: center;
  background: #1f9d61;
  box-shadow: 0 6px 16px rgba(31, 157, 97, 0.35);
}

.track {
  position: relative;
  height: 2.55rem;
  border-radius: 12px;
  border: 1px solid var(--line);
  background: linear-gradient(180deg, #fafafa, #f1f2f5);
  overflow: hidden;
  touch-action: none;
  user-select: none;
  cursor: grab;
  outline: none;
}

.track:active {
  cursor: grabbing;
}

.track[data-disabled='1'] {
  cursor: not-allowed;
  opacity: 0.92;
}

.fill {
  position: absolute;
  inset: 0 auto 0 0;
  background: color-mix(in srgb, var(--brand) 16%, white);
  pointer-events: none;
}

.knob {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 2.25rem;
  height: calc(100% - 6px);
  border-radius: 9px;
  background: linear-gradient(180deg, #ffffff, #f4f5f8);
  border: 1px solid color-mix(in srgb, var(--brand) 32%, var(--line));
  display: grid;
  place-items: center;
  color: var(--brand);
  box-shadow:
    0 1px 2px rgba(15, 23, 42, 0.06),
    0 4px 10px rgba(15, 23, 42, 0.08);
  z-index: 1;
}

.knob-svg {
  width: 1rem;
  height: 1rem;
}

.knob-svg.spin {
  animation: spin 0.8s linear infinite;
}

.track-hint {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: var(--muted);
  font-size: 0.82rem;
  pointer-events: none;
  transition: opacity 140ms var(--ease);
  padding-left: 1.7rem;
}

.track-hint.hidden {
  opacity: 0;
}

.slider-captcha[data-status='ok'] .fill {
  background: color-mix(in srgb, #1f9d61 18%, white);
}

.slider-captcha[data-status='ok'] .knob {
  color: #1f9d61;
  border-color: color-mix(in srgb, #1f9d61 45%, var(--line));
}

.slider-captcha[data-status='fail'] .knob {
  color: var(--danger);
  border-color: color-mix(in srgb, var(--danger) 40%, var(--line));
  animation: captcha-shake 320ms var(--ease);
}

.slider-captcha[data-status='fail'] .track {
  border-color: color-mix(in srgb, var(--danger) 35%, var(--line));
}

@keyframes pop {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes tip-in {
  from {
    opacity: 0;
    transform: translateY(-3px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@keyframes captcha-shake {
  0%,
  100% {
    transform: translateX(0);
  }
  25% {
    transform: translateX(-3px);
  }
  75% {
    transform: translateX(3px);
  }
}

@media (prefers-reduced-motion: reduce) {
  .popup,
  .fail-tip,
  .track-hint,
  .knob-svg.spin,
  .slider-captcha[data-status='fail'] .knob {
    animation: none;
    transition: none;
  }
}
</style>
