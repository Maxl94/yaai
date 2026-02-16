// Auth types
export interface AuthUser {
  id: string
  username: string
  email: string | null
  role: 'owner' | 'viewer'
  auth_provider: 'local' | 'google'
  is_active: boolean
  created_at: string
}

export interface LoginRequest {
  username: string
  password: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  user: AuthUser
}

export interface AuthConfigResponse {
  enabled: boolean
  local_enabled: boolean
  google_oauth_enabled: boolean
  allow_registration: boolean
}

export interface APIKeyItem {
  id: string
  name: string
  key_prefix: string
  is_active: boolean
  last_used_at: string | null
  expires_at: string | null
  created_at: string
  service_account_id: string | null
}

export interface APIKeyCreateResponse {
  api_key: APIKeyItem
  raw_key: string
}

export interface ServiceAccountKeyInfo {
  key_prefix: string
  last_used_at: string | null
  expires_at: string | null
  created_at: string
}

export interface ServiceAccount {
  id: string
  name: string
  description: string | null
  auth_type: string
  google_sa_email: string | null
  is_active: boolean
  created_at: string
  api_key: ServiceAccountKeyInfo | null
}

export interface ServiceAccountCreateResponse {
  service_account: ServiceAccount
  raw_key: string | null
}

export interface ModelAccessEntry {
  id: string
  model_id: string
  service_account_id: string
  created_at: string
  created_by_user_id: string | null
}

// Model types
export interface Model {
  id: string
  name: string
  description: string | null
  created_at: string
  updated_at: string
  versions?: ModelVersionSummary[]
  active_version?: ModelVersionSummary | null
  total_inferences?: number
}

export interface ModelVersionSummary {
  id: string
  version: string
  is_active: boolean
  created_at: string
  schema_field_count?: number
}

export interface ModelVersion {
  id: string
  model_id: string
  version: string
  is_active: boolean
  created_at: string
  schema_fields: SchemaField[]
}

export interface SchemaField {
  id: string
  model_version_id: string
  field_name: string
  direction: 'input' | 'output'
  data_type: 'numerical' | 'categorical'
  drift_metric: string | null
  alert_threshold: number | null
}

export interface SchemaFieldCreate {
  field_name: string
  direction: 'input' | 'output'
  data_type: 'numerical' | 'categorical'
  drift_metric?: string
  alert_threshold?: number
}

// Inference types
export interface Inference {
  id: string
  model_version_id: string
  inputs: Record<string, unknown>
  outputs: Record<string, unknown>
  timestamp: string
  ground_truth: Record<string, unknown> | null
}

// Job types
export interface JobConfig {
  id: string
  model_version_id: string
  name: string
  schedule: string
  comparison_type: 'vs_reference' | 'rolling_window'
  window_size: string
  min_samples: number
  is_active: boolean
  created_at: string
}

export interface JobRun {
  id: string
  job_config_id: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  started_at: string
  completed_at: string | null
  error_message: string | null
}

export interface DriftWindowInfo {
  configured_window_days: number
  actual_window_days: number
  window_extended: boolean
  min_samples: number
  sample_count: number
}

export interface DriftResult {
  id: string
  job_run_id: string | null
  schema_field_id: string
  field_name: string
  metric_name: string
  score: number
  threshold: number
  is_drifted: boolean
  details: Record<string, unknown> & { window?: DriftWindowInfo }
  created_at: string
}

// Notification types
export interface Notification {
  id: string
  model_version_id: string
  title: string
  severity: 'info' | 'warning' | 'error' | 'critical'
  message: string
  is_read: boolean
  created_at: string
}

// Dashboard types
export interface HistogramBucket {
  range_start: number
  range_end: number
  count: number
}

export interface NumericalStatistics {
  mean: number
  median: number
  std: number
  min: number
  max: number
  count: number
  null_count: number
}

export interface HistogramData {
  buckets: HistogramBucket[]
  statistics: NumericalStatistics
}

export interface CategoryCount {
  value: string
  count: number
  percentage: number
}

export interface CategoricalStatistics {
  unique_count: number
  total_count: number
  null_count: number
  top_category: string | null
}

export interface CategoricalData {
  categories: CategoryCount[]
  statistics: CategoricalStatistics
}

export interface LatestDrift {
  metric_name: string
  metric_value: number
  is_drifted: boolean
  calculated_at: string | null
}

export interface DashboardPanel {
  field_name: string
  direction: string
  data_type: string
  chart_type: string
  data: HistogramData | CategoricalData
  latest_drift: LatestDrift | null
}

export interface DashboardResponse {
  model_version_id: string
  time_range: { from: string | null; to: string | null }
  panels: DashboardPanel[]
}

// Comparison types
export interface DriftScore {
  metric_name: string
  metric_value: number
  is_drifted: boolean
  threshold: number
}

export interface ComparisonPanel {
  field_name: string
  direction: string
  data_type: string
  chart_type: string
  data_a: HistogramData | CategoricalData
  data_b: HistogramData | CategoricalData
  drift_score?: DriftScore
}

// Drift Overview types
export interface DriftOverviewItem {
  model_id: string
  model_name: string
  model_description: string | null
  version_id: string
  version: string
  total_inferences: number
  total_fields: number
  drifted_fields: number
  health_percentage: number
  last_check: string | null
  results: DriftResult[]
}

// Inference Volume types
export interface InferenceVolumeBucket {
  bucket: string
  count: number
}

// API response wrapper
export interface ApiResponse<T> {
  data: T
}

export interface PaginatedResponse<T> {
  data: T[]
  meta: {
    total: number
    page: number
    page_size: number
  }
}

// Error types
export interface ApiError {
  status: number
  message: string
  detail?: string
}

export function isApiError(error: unknown): error is ApiError {
  return (
    typeof error === 'object' &&
    error !== null &&
    'status' in error &&
    'message' in error
  )
}
