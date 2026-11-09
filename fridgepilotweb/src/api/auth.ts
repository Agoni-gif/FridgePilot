import { apiRequest } from './http'
import type { AuthUser } from '../stores/auth'

export type AuthTokenResponse = {
  access_token: string
  token_type: string
  user: AuthUser
}

export type CaptchaChallenge = {
  captcha_id: string
  bg_image: string
  piece_image: string
  piece_y: number
  piece_pad: number
  bg_width: number
  bg_height: number
  piece_size: number
}

export function fetchCaptcha(): Promise<CaptchaChallenge> {
  return apiRequest<CaptchaChallenge>('/api/v1/auth/captcha', {
    method: 'GET',
    auth: false,
  })
}

export function verifyCaptcha(payload: {
  captcha_id: string
  captcha_x: number
}): Promise<{ ok: boolean }> {
  return apiRequest<{ ok: boolean }>('/api/v1/auth/captcha/verify', {
    method: 'POST',
    body: payload,
    auth: false,
  })
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
  captcha_id: string
  captcha_x: number
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
