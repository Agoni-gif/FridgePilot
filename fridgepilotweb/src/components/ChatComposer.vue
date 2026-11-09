<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps<{
  disabled: boolean
  draft: string
}>()

const emit = defineEmits<{
  submit: [payload: { message: string }]
  'update:draft': [value: string]
}>()

const message = ref(props.draft)
const focused = ref(false)
const textareaRef = ref<HTMLTextAreaElement | null>(null)

watch(
  () => props.draft,
  async (value) => {
    message.value = value
    await nextTick()
    autoResize()
  },
)

const canSubmit = computed(() => message.value.trim().length > 0 && !props.disabled)

function autoResize() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 160)}px`
}

async function onSubmit() {
  if (!canSubmit.value) return
  const text = message.value.trim()
  message.value = ''
  emit('update:draft', '')
  await nextTick()
  autoResize()
  emit('submit', { message: text })
}
</script>

<template>
  <form class="composer" :class="{ focused, disabled }" @submit.prevent="onSubmit">
    <div class="input-row">
      <textarea
        ref="textareaRef"
        :value="message"
        rows="1"
        maxlength="1000"
        placeholder="发消息或输入食材…"
        :disabled="disabled"
        @focus="focused = true"
        @blur="focused = false"
        @input="
          message = ($event.target as HTMLTextAreaElement).value;
          emit('update:draft', message);
          autoResize()
        "
        @keydown.enter.exact.prevent="onSubmit"
      />
      <button type="submit" class="send" :disabled="!canSubmit" :aria-label="disabled ? '处理中' : '发送'">
        <svg v-if="!disabled" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path
            fill="currentColor"
            d="M3.4 20.6 21 12 3.4 3.4l.1 6.5L14 12 3.5 14.1z"
          />
        </svg>
        <span v-else class="spinner" aria-hidden="true" />
      </button>
    </div>
  </form>
</template>

<style scoped>
.composer {
  border: 1px solid var(--line);
  border-radius: 22px;
  background: var(--bg);
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.06);
  padding: 0.75rem 0.85rem;
  transition: border-color 160ms ease, box-shadow 160ms ease;
}

.composer.focused {
  border-color: color-mix(in srgb, var(--brand) 35%, var(--line));
  box-shadow: 0 10px 32px rgba(0, 0, 0, 0.08);
}

.composer.disabled {
  opacity: 0.85;
}

.input-row {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 0.55rem;
  align-items: end;
}

textarea {
  width: 100%;
  resize: none;
  border: 0;
  padding: 0.45rem 0.2rem;
  min-height: 1.6rem;
  max-height: 160px;
  background: transparent;
  color: var(--ink);
  line-height: 1.55;
  font-size: 0.98rem;
}

textarea::placeholder {
  color: #b0b0b0;
}

textarea:focus {
  outline: none;
}

.send {
  width: 2.2rem;
  height: 2.2rem;
  border: 0;
  border-radius: 999px;
  display: grid;
  place-items: center;
  background: var(--brand);
  color: #fff;
  cursor: pointer;
  transition: background 140ms ease, opacity 140ms ease;
}

.send:hover:not(:disabled) {
  background: var(--brand-hover);
}

.send:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.spinner {
  width: 0.9rem;
  height: 0.9rem;
  border: 2px solid rgba(255, 255, 255, 0.35);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
