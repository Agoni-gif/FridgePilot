import type { PublicContext, SessionMessagesResponse, SessionSummary } from '../types/recipe'
import { apiRequest, ApiError } from './http'

export { ApiError }

export async function listSessions(signal?: AbortSignal): Promise<SessionSummary[]> {
  const data = await apiRequest<{ sessions: SessionSummary[] }>('/api/v1/sessions', {
    signal,
  })
  return data.sessions
}

export async function getSessionMessages(
  sessionId: string,
  signal?: AbortSignal,
): Promise<SessionMessagesResponse> {
  return apiRequest<SessionMessagesResponse>(`/api/v1/sessions/${sessionId}/messages`, {
    signal,
  })
}

export async function getSessionContext(
  sessionId: string,
  signal?: AbortSignal,
): Promise<PublicContext> {
  return apiRequest<PublicContext>(`/api/v1/sessions/${sessionId}/context`, {
    signal,
  })
}

export async function clearSessionContext(sessionId: string): Promise<PublicContext> {
  return apiRequest<PublicContext>(`/api/v1/sessions/${sessionId}/context`, {
    method: 'DELETE',
  })
}

export async function deleteSession(sessionId: string): Promise<void> {
  await apiRequest<void>(`/api/v1/sessions/${sessionId}`, {
    method: 'DELETE',
  })
}
