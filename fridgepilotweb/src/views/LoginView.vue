<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, RouterLink } from 'vue-router'
import { login } from '../api/auth'
import { ApiError } from '../api/http'
import SliderCaptcha from '../components/SliderCaptcha.vue'
import { setAuth } from '../stores/auth'

const router = useRouter()
const account = ref('')
const password = ref('')
const error = ref('')
const busy = ref(false)
const captchaResetKey = ref(0)
const captcha = ref<{ captchaId: string; captchaX: number } | null>(null)

function onCaptchaChange(value: { captchaId: string; captchaX: number } | null) {
  captcha.value = value
}

async function handleSubmit() {
  if (busy.value) return
  error.value = ''
  if (!captcha.value) {
    error.value = '请先完成滑块验证。'
    return
  }
  busy.value = true
  try {
    const res = await login({
      account: account.value.trim(),
      password: password.value,
      captcha_id: captcha.value.captchaId,
      captcha_x: captcha.value.captchaX,
    })
    setAuth(res.access_token, res.user)
    await router.replace('/')
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : '登录失败，请稍后重试。'
    captcha.value = null
    captchaResetKey.value += 1
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="panel">
      <div class="brand">
        <img class="logo" src="/logo-mark.svg" alt="" width="28" height="28" />
        <span class="name">FridgePilot</span>
      </div>
      <h1>登录</h1>
      <p class="lead">使用用户名或邮箱登录后继续使用。</p>

      <form class="form" @submit.prevent="handleSubmit">
        <label>
          <span>用户名或邮箱</span>
          <input v-model="account" type="text" autocomplete="username" required />
        </label>
        <label>
          <span>密码</span>
          <input v-model="password" type="password" autocomplete="current-password" required />
        </label>
        <div class="captcha-wrap">
          <SliderCaptcha :reset-key="captchaResetKey" @change="onCaptchaChange" />
        </div>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
        <button type="submit" class="primary" :disabled="busy || !captcha">
          {{ busy ? '登录中…' : '登录' }}
        </button>
      </form>

      <p class="switch">
        还没有账号？
        <RouterLink to="/register">注册</RouterLink>
      </p>

      <div class="alt" aria-label="其他登录方式（即将开放）">
        <p class="alt-title">其他方式 · 即将开放</p>
        <div class="alt-actions">
          <button type="button" disabled>手机号登录</button>
          <button type="button" disabled>微信</button>
          <button type="button" disabled>GitHub</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.auth-page {
  min-height: 100dvh;
  display: grid;
  place-items: center;
  padding: 1.5rem;
  background:
    radial-gradient(ellipse 80% 50% at 50% -10%, color-mix(in srgb, var(--brand) 14%, white), transparent),
    var(--bg);
}

.panel {
  width: min(100%, 420px);
  animation: fade 420ms var(--ease) both;
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: 0.55rem;
  margin-bottom: 1.5rem;
}

.logo {
  width: 1.7rem;
  height: 1.7rem;
  border-radius: 50%;
  display: block;
  flex-shrink: 0;
}

.name {
  font-size: 1rem;
  font-weight: 650;
  letter-spacing: -0.02em;
}

h1 {
  margin: 0;
  font-size: 1.75rem;
  font-weight: 650;
  letter-spacing: -0.03em;
}

.lead {
  margin: 0.5rem 0 1.4rem;
  color: var(--muted);
  line-height: 1.5;
}

.form {
  display: grid;
  gap: 0.9rem;
}

label,
.captcha-wrap {
  display: grid;
  gap: 0.35rem;
  font-size: 0.88rem;
  color: var(--ink-soft);
}

input {
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 0.75rem 0.9rem;
  background: var(--bg);
  color: var(--ink);
  outline: none;
  transition: border-color 140ms ease, box-shadow 140ms ease;
}

input:focus {
  border-color: color-mix(in srgb, var(--brand) 55%, var(--line));
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--brand) 16%, transparent);
}

.primary {
  margin-top: 0.25rem;
  border: 0;
  border-radius: 12px;
  padding: 0.8rem 1rem;
  background: var(--brand);
  color: #fff;
  font-weight: 600;
  cursor: pointer;
  transition: background 140ms ease;
}

.primary:hover:not(:disabled) {
  background: var(--brand-hover);
}

.primary:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}

.error {
  margin: 0;
  color: var(--danger);
  font-size: 0.88rem;
}

.switch {
  margin: 1.1rem 0 0;
  color: var(--muted);
  font-size: 0.9rem;
}

.switch a {
  color: var(--brand);
  text-decoration: none;
  font-weight: 600;
}

.alt {
  margin-top: 1.6rem;
  padding-top: 1.2rem;
  border-top: 1px solid var(--line);
}

.alt-title {
  margin: 0 0 0.7rem;
  font-size: 0.8rem;
  color: var(--muted);
}

.alt-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.alt-actions button {
  border: 1px solid var(--line);
  background: var(--bg-soft);
  color: var(--muted);
  border-radius: 999px;
  padding: 0.45rem 0.85rem;
  font-size: 0.82rem;
  cursor: not-allowed;
  opacity: 0.75;
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
