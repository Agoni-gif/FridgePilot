export interface PreferenceValues {
  servings: number | null
  max_time_minutes: number | null
  cuisine: string | null
  dietary_restrictions: string[]
  allergies: string[]
}

export interface UserPreferencesResponse {
  enabled: boolean
  preferences: PreferenceValues
  version: number
  updated_at: string | null
  exists: boolean
}
