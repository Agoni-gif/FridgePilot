<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, RouterLink } from 'vue-router'
import { register } from '../api/auth'
import { ApiError } from '../api/http'
import { setAuth } from '../stores/auth'

const router = useRouter()
const username = ref('')
const email = ref('')
const password = ref('')
const error = ref('')
const busy = ref(false)

async function handleSubmit() {
  if (busy.value) return
  error.value = ''
  if (password.value.length < 8) {
    error.value = '密码至少 8 位。'
    return
  }
  busy.value = true
  try {
    const res = await register({
      username: username.value.trim(),
      email: email.value.trim() || null,
      password: password.value,
    })
    setAuth(res.access_token, res.user)
    await router.replace('/')
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : '注册失败，请稍后重试。'
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
      <h1>注册</h1>
      <p class="lead">创建账号后即可开始对话。邮箱可选，也可只用用户名。</p>

      <form class="form" @submit.prevent="handleSubmit">
        <label>
          <span>用户名</span>
          <input
            v-model="username"
            type="text"
            autocomplete="username"
            required
            minlength="3"
            maxlength="32"
            pattern="[A-Za-z0-9_]{3,32}"
            title="3–32 位字母、数字或下划线"
          />
        </label>
        <label>
          <span>邮箱（可选）</span>
          <input v-model="email" type="email" autocomplete="email" />
        </label>
        <label>
          <span>密码</span>
          <input
            v-model="password"
            type="password"
            autocomplete="new-password"
            required
            minlength="8"
          />
        </label>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
        <button type="submit" class="primary" :disabled="busy">
          {{ busy ? '注册中…' : '创建账号' }}
        </button>
      </form>

      <p class="switch">
        已有账号？
        <RouterLink to="/login">登录</RouterLink>
      </p>
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

label {
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
