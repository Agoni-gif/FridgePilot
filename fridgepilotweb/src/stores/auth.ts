import { computed, ref } from 'vue'

const TOKEN_KEY = 'fridgepilot_token'
const USER_KEY = 'fridgepilot_user'

export type AuthUser = {
  id: string
  username: string
  email: string | null
}

function readStoredUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    if (!raw) return null
    return JSON.parse(raw) as AuthUser
  } catch {
    return null
  }
}

const token = ref<string | null>(localStorage.getItem(TOKEN_KEY))
const user = ref<AuthUser | null>(readStoredUser())

export const isAuthenticated = computed(() => !!token.value)

export function getToken(): string | null {
  return token.value
}

export function getUser() {
  return user
}

export function setAuth(accessToken: string, nextUser: AuthUser) {
  token.value = accessToken
  user.value = nextUser
  localStorage.setItem(TOKEN_KEY, accessToken)
  localStorage.setItem(USER_KEY, JSON.stringify(nextUser))
}

export function clearAuth() {
  token.value = null
  user.value = null
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export function useAuth() {
  return {
    token,
    user,
    isAuthenticated,
    setAuth,
    clearAuth,
    getToken,
  }
}
