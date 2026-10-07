// Types mirror the FastAPI response schemas in app/schemas/*.py.
// tests/test_api_contract.py checks that every endpoint used by lib/api-client.ts exists in the backend.

export interface Prompt {
  id: string;
  name: string;
  description: string | null;
  tags: string[];
  created_at: string;
  updated_at: string;
}

export interface PromptSummary extends Prompt {
  version_count: number;
  active_version: string | null;
  active_version_id: string | null;
  latest_version: string | null;
}

export interface PromptVersion {
  id: string;
  prompt_id: string;
  semantic_version: string;
  template: string;
  metadata_json: Record<string, unknown>;
  provider_config: Record<string, unknown>;
  content_hash: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface PromptDetail extends Prompt {
  versions: PromptVersion[];
}

export interface PromptCreate {
  name: string;
  description?: string;
  tags?: string[];
}

export interface VersionCreate {
  semantic_version: string;
  template: string;
  metadata_json?: Record<string, unknown>;
  provider_config?: Record<string, unknown>;
  set_as_active?: boolean;
}

export interface VersionIntegrity {
  version_id: string;
  stored_hash: string;
  computed_hash: string;
  intact: boolean;
}

// Diff
export type DiffOp = 'equal' | 'insert' | 'delete';
export type Granularity = 'token' | 'line' | 'char';

export interface DiffSegment {
  op: DiffOp;
  text: string;
  token_count: number;
}

export interface DiffStats {
  added: number;
  removed: number;
  unchanged: number;
  similarity: number;
}

export interface TokenDiff {
  granularity: Granularity;
  tokenizer: string;
  approximate_tokenizer: boolean;
  algorithm: string;
  coarse: boolean;
  original_units: number;
  modified_units: number;
  original_tokens: number;
  modified_tokens: number;
  stats: DiffStats;
  segments: DiffSegment[];
}

export interface PromptDiff {
  prompt_id: string;
  version_a: PromptVersion;
  version_b: PromptVersion;
  template_diff: TokenDiff;
  variables: { added: string[]; removed: string[]; unchanged: string[] };
  config_diff: Record<string, { before: unknown; after: unknown }>;
  metadata_diff: Record<string, { before: unknown; after: unknown }>;
}

export interface ChangelogEntry {
  version_id: string;
  semantic_version: string;
  content_hash: string;
  is_active: boolean;
  created_at: string;
  previous_version: string | null;
  diff_stats: DiffStats | null;
  tokenizer: string | null;
}

// Audit
export interface AuditEvent {
  id: string;
  seq: number;
  occurred_at: string;
  actor_id: string;
  request_id: string | null;
  entity_type: string;
  entity_id: string;
  action: string;
  before_state: Record<string, unknown> | null;
  after_state: Record<string, unknown> | null;
  content_hash: string | null;
  prev_hash: string;
  event_hash: string;
}

export interface AuditVerification {
  valid: boolean;
  events_checked: number;
  head_seq: number | null;
  head_hash: string | null;
  errors: { seq: number; kind: string; detail: string }[];
}

// Datasets
export interface EvaluationCase {
  id: string;
  dataset_id: string;
  ordinal: number;
  input_text: string;
  expected_behavior: Record<string, unknown>;
  created_at: string;
}

export interface EvaluationDataset {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  case_count: number;
}

export interface EvaluationDatasetDetail extends EvaluationDataset {
  cases: EvaluationCase[];
}

export interface Rubric {
  id: string;
  name: string;
  version: number;
  description: string | null;
  scale_min: number;
  scale_max: number;
  criteria: { name: string; description: string; weight: number }[];
  definition_hash: string;
}

// Evaluation
export type RunStatus = 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED';

export interface RunSettings {
  case_concurrency?: number;
  max_inflight_requests?: number;
  requests_per_second?: number;
  call_timeout_s?: number;
  max_retries?: number;
  judge_max_attempts?: number;
  judge_position_strategy?: 'both' | 'alternate' | 'none';
  judge_include_prompts?: boolean;
}

export interface EvaluationRunCreate {
  dataset_id: string;
  prompt_version_a_id: string;
  prompt_version_b_id: string;
  provider: string;
  model: string;
  judge_provider?: string;
  judge_model?: string;
  rubric_id?: string;
  settings?: RunSettings;
}

export interface EvaluationRun {
  id: string;
  dataset_id: string;
  prompt_version_a_id: string;
  prompt_version_b_id: string;
  rubric_id: string;
  provider: string;
  model: string;
  judge_provider: string;
  judge_model: string;
  config: Record<string, unknown>;
  status: RunStatus;
  cancel_requested: boolean;
  attempts: number;
  error: string | null;
  total_cases: number;
  created_by: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  version_a_label: string | null;
  version_b_label: string | null;
  dataset_name: string | null;
  progress: { total_cases: number; completed_cases: number; failed_cases: number } | null;
}

export interface CandidateOutput {
  id: string;
  slot: 'A' | 'B';
  prompt_version_id: string;
  status: string;
  error: string | null;
  rendered_prompt: string;
  output_text: string | null;
  provider: string;
  model: string;
  generation_params: Record<string, unknown>;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost: number;
  latency_ms: number;
  attempts: number;
  started_at: string;
  completed_at: string;
}

export interface RubricScore {
  criterion: string;
  score_a: number;
  score_b: number;
  reason: string | null;
}

export interface JudgeEvaluation {
  id: string;
  pass_index: number;
  swapped: boolean;
  judge_provider: string;
  judge_model: string;
  rubric_version: number;
  status: string;
  error: string | null;
  winner: 'A' | 'B' | 'TIE' | null;
  score_a: number | null;
  score_b: number | null;
  normalized_score_a: number | null;
  normalized_score_b: number | null;
  confidence: number | null;
  reasoning: string | null;
  raw_score: Record<string, unknown> | null;
  attempts: number;
  prompt_tokens: number;
  completion_tokens: number;
  estimated_cost: number;
  latency_ms: number;
  judged_at: string;
  rubric_scores: RubricScore[];
}

export interface CaseResult {
  result_id: string;
  case_id: string;
  ordinal: number;
  input_text: string;
  expected_behavior: Record<string, unknown>;
  status: 'COMPLETED' | 'FAILED';
  error: string | null;
  winner: 'A' | 'B' | 'TIE' | null;
  score_a: number | null;
  score_b: number | null;
  confidence: number | null;
  position_consistent: boolean | null;
  outputs: CandidateOutput[];
  judge_evaluations: JudgeEvaluation[];
}

export interface SlotMetrics {
  outputs_completed: number;
  outputs_failed: number;
  avg_latency_ms: number | null;
  p95_latency_ms: number | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost: number;
  avg_score: number | null;
}

export interface RunSummary {
  run_id: string;
  status: RunStatus;
  total_cases: number;
  completed_cases: number;
  failed_cases: number;
  wins_a: number;
  wins_b: number;
  ties: number;
  win_rate_a: number | null;
  win_rate_b: number | null;
  tie_rate: number | null;
  a_share_of_decisive: number | null;
  a_share_ci_low: number | null;
  a_share_ci_high: number | null;
  avg_confidence: number | null;
  position_consistency_rate: number | null;
  rubric_scale_min: number;
  rubric_scale_max: number;
  slot_a: SlotMetrics;
  slot_b: SlotMetrics;
  criteria: { criterion: string; avg_score_a: number; avg_score_b: number; samples: number }[];
  judge_tokens: number;
  judge_cost: number;
  total_cost: number;
  note: string;
}
