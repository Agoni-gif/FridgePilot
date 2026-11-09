<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'
import { login } from '../api/auth'
import { ApiError } from '../api/http'
import AuthLayout from '../components/AuthLayout.vue'
import SliderCaptcha from '../components/SliderCaptcha.vue'
import { setAuth } from '../stores/auth'

const route = useRoute()
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
    const raw = typeof route.query.redirect === 'string' ? route.query.redirect : ''
    const redirect = raw.startsWith('/') && !raw.startsWith('//') ? raw : '/'
    await router.replace(redirect)
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
  <AuthLayout
    side-title="从冰箱到下一餐"
    side-lead="记下食材，发现做法。登录后继续你的厨房对话。"
  >
    <form class="auth-form" @submit.prevent="handleSubmit">
      <label>
        <span class="field-label">用户名或邮箱</span>
        <input
          v-model="account"
          type="text"
          autocomplete="username"
          placeholder="请输入用户名或邮箱"
          required
        />
      </label>
      <label>
        <span class="field-label">密码</span>
        <input
          v-model="password"
          type="password"
          autocomplete="current-password"
          placeholder="请输入密码"
          required
        />
      </label>
      <div class="captcha-wrap">
        <SliderCaptcha :reset-key="captchaResetKey" @change="onCaptchaChange" />
      </div>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <button type="submit" class="primary" :disabled="busy || !captcha">
        {{ busy ? '登录中…' : '登录' }}
      </button>
    </form>

    <p class="auth-note">
      还没有账号？
      <RouterLink to="/register">注册</RouterLink>
    </p>
  </AuthLayout>
</template>
