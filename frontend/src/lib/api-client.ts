import { API_CONFIG } from '@/lib/api-config';
import type {
  AuditEvent,
  AuditVerification,
  CaseResult,
  ChangelogEntry,
  EvaluationCase,
  EvaluationDataset,
  EvaluationDatasetDetail,
  EvaluationRun,
  EvaluationRunCreate,
  Granularity,
  Prompt,
  PromptCreate,
  PromptDetail,
  PromptDiff,
  PromptSummary,
  PromptVersion,
  Rubric,
  RunSummary,
  VersionCreate,
  VersionIntegrity,
} from '@/types/api';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

class ApiClient {
  private baseUrl = API_CONFIG.baseURL;

  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (API_CONFIG.apiKey) headers['X-API-Key'] = API_CONFIG.apiKey;
    if (API_CONFIG.actorId) headers['X-Actor-Id'] = API_CONFIG.actorId;
    const response = await fetch(`${this.baseUrl}${endpoint}`, {
      ...options,
      headers: { ...headers, ...(options.headers as Record<string, string> | undefined) },
    });
    if (!response.ok) {
      let message = `${response.status} ${response.statusText}`;
      try {
        const body = await response.json();
        message = body?.error?.message ?? (typeof body?.detail === 'string' ? body.detail : message);
      } catch {
        /* non-JSON error body */
      }
      throw new ApiError(response.status, message);
    }
    return response.json();
  }

  private post<T>(endpoint: string, body?: unknown): Promise<T> {
    return this.request<T>(endpoint, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) });
  }

  // Prompts
  getPrompts() {
    return this.request<PromptSummary[]>('/prompts');
  }
  getPrompt(id: string) {
    return this.request<PromptDetail>(`/prompts/${id}`);
  }
  createPrompt(data: PromptCreate) {
    return this.post<Prompt>('/prompts', data);
  }

  // Versions
  getVersions(promptId: string) {
    return this.request<PromptVersion[]>(`/prompts/${promptId}/versions`);
  }
  createVersion(promptId: string, data: VersionCreate) {
    return this.post<PromptVersion>(`/prompts/${promptId}/versions`, data);
  }
  activateVersion(promptId: string, versionId: string) {
    return this.post<PromptVersion>(`/prompts/${promptId}/versions/${versionId}/activate`);
  }
  rollbackPrompt(promptId: string, targetVersionId: string) {
    return this.post<PromptVersion>(`/prompts/${promptId}/rollback`, { target_version_id: targetVersionId });
  }
  verifyVersion(promptId: string, versionId: string) {
    return this.request<VersionIntegrity>(`/prompts/${promptId}/versions/${versionId}/integrity`);
  }
  getPromptDiff(promptId: string, a: string, b: string, granularity: Granularity = 'token', model?: string) {
    const q = new URLSearchParams({ version_a_id: a, version_b_id: b, granularity });
    if (model) q.set('model', model);
    return this.request<PromptDiff>(`/prompts/${promptId}/diff?${q.toString()}`);
  }
  getChangelog(promptId: string) {
    return this.request<ChangelogEntry[]>(`/prompts/${promptId}/changelog`);
  }
  getPromptAudit(promptId: string) {
    return this.request<AuditEvent[]>(`/prompts/${promptId}/audit`);
  }

  // Audit
  verifyAuditChain() {
    return this.request<AuditVerification>('/audit/verify');
  }

  // Datasets
  getDatasets() {
    return this.request<EvaluationDataset[]>('/datasets');
  }
  getDataset(id: string) {
    return this.request<EvaluationDatasetDetail>(`/datasets/${id}`);
  }
  createDataset(data: { name: string; description?: string }) {
    return this.post<EvaluationDataset>('/datasets', data);
  }
  addCase(datasetId: string, data: { input_text: string; expected_behavior: Record<string, unknown> }) {
    return this.post<EvaluationCase>(`/datasets/${datasetId}/cases`, data);
  }

  // Evaluations
  getRubrics() {
    return this.request<Rubric[]>('/evaluations/rubrics');
  }
  getRuns() {
    return this.request<EvaluationRun[]>('/evaluations/runs');
  }
  getRun(id: string) {
    return this.request<EvaluationRun>(`/evaluations/runs/${id}`);
  }
  createRun(data: EvaluationRunCreate) {
    return this.post<EvaluationRun>('/evaluations/runs', data);
  }
  cancelRun(id: string) {
    return this.post<EvaluationRun>(`/evaluations/runs/${id}/cancel`);
  }
  getRunSummary(id: string) {
    return this.request<RunSummary>(`/evaluations/runs/${id}/summary`);
  }
  getRunCases(id: string) {
    return this.request<CaseResult[]>(`/evaluations/runs/${id}/cases`);
  }
}

export const apiClient = new ApiClient();
