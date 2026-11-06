export type Confidence = 'low' | 'medium' | 'high'

export interface RecipeSource {
  title: string
  url: string
}

export interface Recipe {
  title: string
  summary: string
  prep_time_minutes: number | null
  cook_time_minutes: number | null
  servings: number | null
  ingredients: string[]
  steps: string[]
  tips: string[]
  sources: RecipeSource[]
  confidence: Confidence
}

export interface ChatPreferences {
  max_time_minutes: number | null
  servings: number | null
  dietary_restrictions: string[]
}

export interface ChatMeta {
  search_used: boolean
  elapsed_ms: number
  prompt_version?: string | null
  detail?: string | null
}

export type ChatStatus = 'completed' | 'insufficient_sources' | 'error'

export interface ChatResponse {
  session_id: string
  status: ChatStatus
  recipe: Recipe | null
  message: string | null
  meta: ChatMeta
}

export type UiPhase = 'idle' | 'parsing' | 'searching' | 'summarizing' | 'done'

export interface ChatMessageItem {
  id: string
  role: 'user' | 'status' | 'assistant' | 'error'
  text?: string
  recipe?: Recipe
  phase?: UiPhase
}
