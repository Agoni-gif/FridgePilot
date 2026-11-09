import { getToken, clearAuth } from '../stores/auth'
import type { ChatPreferences, ChatResponse, PreferencePatch } from '../types/recipe'
import { ApiError } from './http'

export { ApiError }

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

function buildPreferencesPayload(preferences?: ChatPreferences | null): ChatPreferences | undefined {
  if (!preferences) return undefined
  const payload: ChatPreferences = {}
  if (preferences.max_time_minutes != null) {
    payload.max_time_minutes = preferences.max_time_minutes
  }
  if (preferences.servings != null) {
    payload.servings = preferences.servings
  }
  if (preferences.dietary_restrictions && preferences.dietary_restrictions.length > 0) {
    payload.dietary_restrictions = preferences.dietary_restrictions
  }
  return Object.keys(payload).length > 0 ? payload : undefined
}

export async function postChat(params: {
  message: string
  sessionId: string | null
  preferences?: ChatPreferences | null
  preferencePatch?: PreferencePatch | null
  signal?: AbortSignal
  onThinking?: (content: string) => void
}): Promise<ChatResponse> {
  const token = getToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  }
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  const body: Record<string, unknown> = {
    message: params.message,
    session_id: params.sessionId,
  }
  const preferences = buildPreferencesPayload(params.preferences)
  if (preferences) {
    body.preferences = preferences
  }
  if (params.preferencePatch) {
    body.preference_patch = params.preferencePatch
  }

  const res = await fetch(`${API_BASE}/api/v1/chat/stream`, {
    method: 'POST',
    headers,
    signal: params.signal,
    body: JSON.stringify(body),
  })

  if (res.status === 401) {
    clearAuth()
    if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
      window.location.assign('/login')
    }
  }

  if (!res.ok) {
    const data = await res.json().catch(() => null)
    throw new ApiError(
      data?.error?.code ?? 'HTTP_ERROR',
      data?.error?.message ?? '请求失败，请稍后重试。',
      res.status,
    )
  }

  if (!res.body) {
    throw new ApiError('HTTP_ERROR', '流式响应不可用，请稍后重试。', 500)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let finalResponse: ChatResponse | null = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let splitAt = buffer.indexOf('\n\n')
    while (splitAt !== -1) {
      const rawEvent = buffer.slice(0, splitAt)
      buffer = buffer.slice(splitAt + 2)
      const dataLine = rawEvent
        .split('\n')
        .map((line) => line.trimEnd())
        .find((line) => line.startsWith('data:'))
      if (dataLine) {
        const payload = dataLine.replace(/^data:\s*/, '')
        try {
          const event = JSON.parse(payload) as {
            type: string
            content?: string
            data?: ChatResponse
            code?: string
            message?: string
          }
          if (event.type === 'thinking' && event.content) {
            params.onThinking?.(event.content)
          } else if (event.type === 'done' && event.data) {
            finalResponse = event.data
          } else if (event.type === 'error') {
            const code = event.code ?? 'HTTP_ERROR'
            const status = code === 'SESSION_BUSY' || code === 'SESSION_CONFLICT' ? 409 : 400
            throw new ApiError(code, event.message ?? '请求失败', status)
          }
        } catch (err) {
          if (err instanceof ApiError) throw err
        }
      }
      splitAt = buffer.indexOf('\n\n')
    }
  }

  if (!finalResponse) {
    throw new ApiError('HTTP_ERROR', '未收到完整回复，请重试。', 500)
  }
  return finalResponse
}
