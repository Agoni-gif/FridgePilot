<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { ChatPreferences } from '../types/recipe'

const props = defineProps<{
  disabled: boolean
  draft: string
}>()

const emit = defineEmits<{
  submit: [payload: { message: string; preferences: ChatPreferences }]
  'update:draft': [value: string]
}>()

const message = ref(props.draft)
const maxTime = ref<number | null>(20)
const servings = ref<number | null>(2)
const restrictions = ref('')
const focused = ref(false)

watch(
  () => props.draft,
  (value) => {
    message.value = value
  },
)

const canSubmit = computed(() => message.value.trim().length > 0 && !props.disabled)
const charCount = computed(() => message.value.length)

function onSubmit() {
  if (!canSubmit.value) return
  const dietary = restrictions.value
    .split(/[,，、]/)
    .map((s) => s.trim())
    .filter(Boolean)

  emit('submit', {
    message: message.value.trim(),
    preferences: {
      max_time_minutes: maxTime.value,
      servings: servings.value,
      dietary_restrictions: dietary,
    },
  })
}
</script>

<template>
  <form class="composer" :class="{ focused, disabled }" @submit.prevent="onSubmit">
    <div class="rail">
      <div class="pref">
        <span class="label">人数</span>
        <div class="stepper">
          <button type="button" :disabled="disabled || (servings ?? 1) <= 1" @click="servings = Math.max(1, (servings ?? 1) - 1)">−</button>
          <input v-model.number="servings" type="number" min="1" max="20" :disabled="disabled" />
          <button type="button" :disabled="disabled || (servings ?? 1) >= 20" @click="servings = Math.min(20, (servings ?? 1) + 1)">+</button>
        </div>
      </div>

      <div class="pref">
        <span class="label">分钟</span>
        <div class="stepper">
          <button type="button" :disabled="disabled || (maxTime ?? 5) <= 5" @click="maxTime = Math.max(5, (maxTime ?? 20) - 5)">−</button>
          <input v-model.number="maxTime" type="number" min="1" max="300" :disabled="disabled" />
          <button type="button" :disabled="disabled || (maxTime ?? 20) >= 300" @click="maxTime = Math.min(300, (maxTime ?? 20) + 5)">+</button>
        </div>
      </div>

      <label class="pref diet">
        <span class="label">忌口</span>
        <input
          v-model="restrictions"
          type="text"
          placeholder="可选，如不吃辣"
          :disabled="disabled"
        />
      </label>
    </div>

    <div class="well">
      <textarea
        :value="message"
        rows="3"
        maxlength="1000"
        placeholder="说说冰箱里有什么，想做成怎样的一餐…"
        :disabled="disabled"
        @focus="focused = true"
        @blur="focused = false"
        @input="
          message = ($event.target as HTMLTextAreaElement).value;
          emit('update:draft', message)
        "
        @keydown.enter.exact.prevent="onSubmit"
      />

      <div class="toolbar">
        <p class="hint">
          <span>Enter 发送</span>
          <span class="sep">·</span>
          <span :class="{ warn: charCount > 900 }">{{ charCount }} / 1000</span>
        </p>
        <button type="submit" class="send" :disabled="!canSubmit">
          {{ disabled ? '检索中…' : '开始找菜' }}
        </button>
      </div>
    </div>
  </form>
</template>

<style scoped>
.composer {
  display: grid;
  border-radius: 16px;
  border: 1px solid var(--line);
  background: #fff;
  overflow: hidden;
  transition: border-color 180ms ease, box-shadow 180ms ease;
}

.composer.focused {
  border-color: color-mix(in srgb, var(--accent) 45%, var(--line));
  box-shadow: 0 0 0 3px var(--accent-wash);
}

.composer.disabled {
  opacity: 0.78;
}

.rail {
  display: grid;
  grid-template-columns: auto auto minmax(0, 1fr);
  gap: 0.75rem;
  align-items: end;
  padding: 0.85rem 1rem;
  background: #f4f6f9;
  border-bottom: 1px solid var(--line);
}

.pref {
  display: grid;
  gap: 0.35rem;
  min-width: 0;
}

.label {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--muted);
  letter-spacing: 0.02em;
}

.stepper {
  display: inline-grid;
  grid-template-columns: 2rem 2.75rem 2rem;
  align-items: center;
  height: 2.4rem;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fff;
  overflow: hidden;
}

.stepper button {
  height: 100%;
  border: 0;
  background: transparent;
  color: var(--ink-soft);
  font-size: 1rem;
  line-height: 1;
  cursor: pointer;
}

.stepper button:hover:not(:disabled) {
  background: #eef2f6;
  color: var(--ink);
}

.stepper button:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.stepper input {
  width: 100%;
  height: 100%;
  border: 0;
  border-left: 1px solid var(--line);
  border-right: 1px solid var(--line);
  text-align: center;
  background: transparent;
  color: var(--ink);
  font-weight: 600;
  /* hide native number spinners that squash the field */
  -moz-appearance: textfield;
  appearance: textfield;
}

.stepper input::-webkit-outer-spin-button,
.stepper input::-webkit-inner-spin-button {
  -webkit-appearance: none;
  margin: 0;
}

.diet input {
  width: 100%;
  height: 2.4rem;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 0 0.75rem;
  background: #fff;
  color: var(--ink);
}

.diet input:focus,
.stepper input:focus {
  outline: none;
}

.diet input:focus {
  border-color: color-mix(in srgb, var(--accent) 45%, var(--line));
}

.well {
  display: grid;
  gap: 0.65rem;
  padding: 0.9rem 1rem 0.95rem;
}

textarea {
  width: 100%;
  resize: none;
  min-height: 4.8rem;
  max-height: 9rem;
  border: 0;
  padding: 0;
  background: transparent;
  color: var(--ink);
  line-height: 1.6;
  font-size: 1rem;
}

textarea::placeholder {
  color: var(--muted);
}

textarea:focus {
  outline: none;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.hint {
  margin: 0;
  font-size: 0.78rem;
  color: var(--muted);
}

.sep {
  margin: 0 0.2rem;
}

.warn {
  color: var(--danger);
}

.send {
  border: 0;
  border-radius: 10px;
  min-height: 2.5rem;
  padding: 0 1.15rem;
  background: var(--ink);
  color: #fff;
  font-weight: 650;
  cursor: pointer;
  transition: background 160ms ease, opacity 160ms ease;
}

.send:hover:not(:disabled) {
  background: color-mix(in srgb, var(--ink) 88%, var(--accent));
}

.send:disabled {
  opacity: 0.38;
  cursor: not-allowed;
}

@media (max-width: 640px) {
  .rail {
    grid-template-columns: 1fr 1fr;
  }

  .diet {
    grid-column: 1 / -1;
  }

  .toolbar {
    flex-wrap: wrap;
  }

  .send {
    margin-left: auto;
  }
}
</style>
