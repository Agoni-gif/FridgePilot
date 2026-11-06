import type { ChatPreferences, ChatResponse } from '../types/recipe'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

export class ApiError extends Error {
  code: string

  constructor(code: string, message: string) {
    super(message)
    this.code = code
  }
}

export async function postChat(params: {
  message: string
  sessionId: string | null
  preferences: ChatPreferences
  signal?: AbortSignal
}): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE}/api/v1/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal: params.signal,
    body: JSON.stringify({
      message: params.message,
      session_id: params.sessionId,
      preferences: {
        max_time_minutes: params.preferences.max_time_minutes,
        servings: params.preferences.servings,
        dietary_restrictions: params.preferences.dietary_restrictions,
      },
    }),
  })

  const data = await res.json().catch(() => null)

  if (!res.ok) {
    const code = data?.error?.code ?? 'HTTP_ERROR'
    const message = data?.error?.message ?? '请求失败，请稍后重试。'
    throw new ApiError(code, message)
  }

  return data as ChatResponse
}
