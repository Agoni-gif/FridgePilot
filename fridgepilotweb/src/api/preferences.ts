import type { PreferenceValues, UserPreferencesResponse } from '../types/preferences'
import { apiRequest, ApiError } from './http'

export { ApiError }

export async function getMyPreferences(signal?: AbortSignal): Promise<UserPreferencesResponse> {
  return apiRequest<UserPreferencesResponse>('/api/v1/me/preferences', { signal })
}

export async function patchMyPreferences(body: {
  version: number
  enabled?: boolean
  set?: Partial<PreferenceValues>
  clear?: string[]
}): Promise<UserPreferencesResponse> {
  return apiRequest<UserPreferencesResponse>('/api/v1/me/preferences', {
    method: 'PATCH',
    body,
  })
}

export async function deleteMyPreferences(): Promise<UserPreferencesResponse> {
  return apiRequest<UserPreferencesResponse>('/api/v1/me/preferences', {
    method: 'DELETE',
  })
}
