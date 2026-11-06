import type { ChatPreferences, ChatResponse } from '../types/recipe'
import { apiRequest, ApiError } from './http'

export { ApiError }

export async function postChat(params: {
  message: string
  sessionId: string | null
  preferences: ChatPreferences
  signal?: AbortSignal
}): Promise<ChatResponse> {
  return apiRequest<ChatResponse>('/api/v1/chat', {
    method: 'POST',
    signal: params.signal,
    body: {
      message: params.message,
      session_id: params.sessionId,
      preferences: {
        max_time_minutes: params.preferences.max_time_minutes,
        servings: params.preferences.servings,
        dietary_restrictions: params.preferences.dietary_restrictions,
      },
    },
  })
}
