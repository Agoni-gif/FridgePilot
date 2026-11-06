import { apiRequest } from './http'
import type { AuthUser } from '../stores/auth'

export type AuthTokenResponse = {
  access_token: string
  token_type: string
  user: AuthUser
}

export function register(payload: {
  username: string
  password: string
  email?: string | null
}): Promise<AuthTokenResponse> {
  return apiRequest<AuthTokenResponse>('/api/v1/auth/register', {
    method: 'POST',
    body: {
      username: payload.username,
      password: payload.password,
      email: payload.email || null,
    },
    auth: false,
  })
}

export function login(payload: {
  account: string
  password: string
}): Promise<AuthTokenResponse> {
  return apiRequest<AuthTokenResponse>('/api/v1/auth/login', {
    method: 'POST',
    body: payload,
    auth: false,
  })
}

export function fetchMe(): Promise<AuthUser> {
  return apiRequest<AuthUser>('/api/v1/auth/me')
}

export function logout(): Promise<void> {
  return apiRequest<void>('/api/v1/auth/logout', { method: 'POST' })
}
