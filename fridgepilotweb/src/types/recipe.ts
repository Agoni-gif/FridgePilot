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
  max_time_minutes?: number | null
  servings?: number | null
  dietary_restrictions?: string[]
}

export interface PreferencePatch {
  set?: Record<string, unknown>
  clear?: string[]
}

export interface SessionIngredient {
  name: string
  quantity?: string | null
}

export interface SessionState {
  schema_version: number
  ingredients: SessionIngredient[]
  meal?: string | null
  servings?: number | null
  max_time_minutes?: number | null
  cuisine?: string | null
  dietary_restrictions: string[]
  excluded_recipe_titles: string[]
  last_recipe_id?: number | null
}

export interface PublicContext {
  context_version: number
  context_start_message_id?: number | null
  state: SessionState | null
  long_term_preferences_applied: boolean
  long_term_preferences_version?: number | null
}

export interface ChatMeta {
  search_used: boolean
  elapsed_ms: number
  prompt_version?: string | null
  detail?: string | null
}

export type ChatStatus = 'completed' | 'insufficient_sources' | 'error' | 'clarification'

export interface ChatResponse {
  session_id: string
  status: ChatStatus
  recipe: Recipe | null
  message: string | null
  thinking?: string | null
  meta: ChatMeta
  context?: PublicContext | null
}

export type UiPhase = 'idle' | 'parsing' | 'searching' | 'summarizing' | 'done'

export interface ThinkingState {
  content?: string
  running: boolean
  elapsedMs?: number
  defaultOpen?: boolean
}

export interface ChatMessageItem {
  id: string
  role: 'user' | 'status' | 'assistant' | 'error' | 'divider'
  text?: string
  recipe?: Recipe
  phase?: UiPhase
  thinking?: ThinkingState
}

export interface SessionSummary {
  id: string
  title: string
  created_at: string
  last_active_at: string
}

export interface SessionMessage {
  id: number
  role: string
  content: string
  thinking?: string | null
  created_at: string
  recipe: Recipe | null
}

export interface SessionMessagesResponse {
  session_id: string
  title: string
  messages: SessionMessage[]
}
