<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, RouterLink } from 'vue-router'
import { register } from '../api/auth'
import { ApiError } from '../api/http'
import AuthLayout from '../components/AuthLayout.vue'
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
  <AuthLayout
    side-title="开始你的厨房助手"
    side-lead="创建一个账号，把冰箱里的食材变成可做的菜。"
  >
    <form class="auth-form" @submit.prevent="handleSubmit">
      <label>
        <span class="field-label">用户名</span>
        <input
          v-model="username"
          type="text"
          autocomplete="username"
          placeholder="3–32 位字母、数字或下划线"
          required
          minlength="3"
          maxlength="32"
          pattern="[A-Za-z0-9_]{3,32}"
          title="3–32 位字母、数字或下划线"
        />
      </label>
      <label>
        <span class="field-label">邮箱（可选）</span>
        <input
          v-model="email"
          type="email"
          autocomplete="email"
          placeholder="可选，用于找回与通知"
        />
      </label>
      <label>
        <span class="field-label">密码</span>
        <input
          v-model="password"
          type="password"
          autocomplete="new-password"
          placeholder="至少 8 位"
          required
          minlength="8"
        />
      </label>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <button type="submit" class="primary" :disabled="busy">
        {{ busy ? '注册中…' : '创建账号' }}
      </button>
    </form>

    <p class="auth-note">
      已有账号？
      <RouterLink to="/login">登录</RouterLink>
    </p>
  </AuthLayout>
</template>
