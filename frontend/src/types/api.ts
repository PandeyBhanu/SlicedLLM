// Prompt Types
export interface Prompt {
  id: string;
  name: string;
  description: string | null;
  tags: string[];
  created_at: string;
  updated_at: string;
}

export interface PromptVersion {
  id: string;
  prompt_id: string;
  semantic_version: string;
  template: string;
  metadata: Record<string, unknown>;
  provider_config: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
}

export interface PromptCreate {
  name: string;
  description?: string;
  tags?: string[];
}

export interface PromptUpdate {
  name?: string;
  description?: string;
  tags?: string[];
}

export interface VersionCreate {
  semantic_version: string;
  template: string;
  metadata?: Record<string, unknown>;
  provider_config?: Record<string, unknown>;
  set_as_active?: boolean;
}

// Evaluation Types
export interface EvaluationDataset {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  cases: EvaluationCase[];
}

export interface EvaluationCase {
  id: string;
  dataset_id: string;
  input_text: string;
  expected_behavior: Record<string, unknown>;
  created_at: string;
}

export interface EvaluationRun {
  id: string;
  prompt_version_a_id: string;
  prompt_version_b_id: string | null;
  provider: string;
  model: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  results: EvaluationResult[];
}

export interface EvaluationResult {
  id: string;
  evaluation_run_id: string;
  evaluation_case_id: string;
  winner: string | null;
  confidence_score: number;
  reasoning: string | null;
  latency_ms: number;
  token_usage: Record<string, unknown>;
  estimated_cost: number;
  created_at: string;
}

export interface EvaluationRunCreate {
  dataset_id: string;
  prompt_version_a_id: string;
  prompt_version_b_id?: string;
  provider: string;
  model: string;
}

// PromptOps Types
export interface ChangelogEntry {
  version_id: string;
  semantic_version: string;
  timestamp: string | null;
  is_active: boolean;
  change_type: string;
  description: string;
  metadata: Record<string, unknown>;
  provider_config: Record<string, unknown>;
  diff?: PromptDiff;
}

export interface PromptDiff {
  diff: DiffResult;
  variables: VariableDiff;
}

export interface DiffResult {
  original: string;
  modified: string;
  segments: DiffSegment[];
  additions: number;
  deletions: number;
  unchanged: number;
  similarity_ratio: number;
}

export interface DiffSegment {
  change_type: string;
  content: string;
  position: number;
  length: number;
}

export interface VariableDiff {
  original: string[];
  modified: string[];
  added: string[];
  removed: string[];
  unchanged: string[];
}

export interface AuditLogEntry {
  audit_log_id: string;
  entity_type: string;
  entity_id: string;
  action: string;
  timestamp: string | null;
  before_state: Record<string, unknown> | null;
  after_state: Record<string, unknown> | null;
}

export interface PromptStatistics {
  prompt_id: string;
  name: string;
  description: string | null;
  tags: string[];
  total_versions: number;
  active_version_id: string | null;
  active_version: string | null;
  latest_version_id: string | null;
  latest_version: string | null;
  created_at: string | null;
  updated_at: string | null;
}

// Provider Types
export interface ProviderConfig {
  provider: string;
  temperature?: number;
  max_tokens?: number;
  top_p?: number;
  frequency_penalty?: number;
  presence_penalty?: number;
}
