import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/lib/api-client';
import type {
  EvaluationRun,
  EvaluationRunCreate,
  Granularity,
  PromptCreate,
  VersionCreate,
} from '@/types/api';

const ACTIVE = ['PENDING', 'RUNNING'];
const isActive = (run?: EvaluationRun) => !!run && ACTIVE.includes(run.status);

// Prompts
export const usePrompts = () => useQuery({ queryKey: ['prompts'], queryFn: () => apiClient.getPrompts() });

export function useCreatePrompt() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: PromptCreate) => apiClient.createPrompt(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['prompts'] }),
  });
}

export const useVersions = (promptId: string) =>
  useQuery({
    queryKey: ['versions', promptId],
    queryFn: () => apiClient.getVersions(promptId),
    enabled: !!promptId,
  });

function useVersionMutation<T>(fn: (v: T) => Promise<unknown>, promptIdOf: (v: T) => string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (_d, vars) => {
      const promptId = promptIdOf(vars);
      qc.invalidateQueries({ queryKey: ['versions', promptId] });
      qc.invalidateQueries({ queryKey: ['prompts'] });
      qc.invalidateQueries({ queryKey: ['changelog', promptId] });
      qc.invalidateQueries({ queryKey: ['prompt-audit', promptId] });
    },
  });
}

export const useCreateVersion = () =>
  useVersionMutation<{ promptId: string; data: VersionCreate }>(
    (v) => apiClient.createVersion(v.promptId, v.data),
    (v) => v.promptId
  );
export const useActivateVersion = () =>
  useVersionMutation<{ promptId: string; versionId: string }>(
    (v) => apiClient.activateVersion(v.promptId, v.versionId),
    (v) => v.promptId
  );
export const useRollbackPrompt = () =>
  useVersionMutation<{ promptId: string; versionId: string }>(
    (v) => apiClient.rollbackPrompt(v.promptId, v.versionId),
    (v) => v.promptId
  );

export const useVersionIntegrity = (promptId: string, versionId: string, enabled: boolean) =>
  useQuery({
    queryKey: ['integrity', promptId, versionId],
    queryFn: () => apiClient.verifyVersion(promptId, versionId),
    enabled: enabled && !!promptId && !!versionId,
  });

export const usePromptDiff = (
  promptId: string,
  a: string,
  b: string,
  granularity: Granularity,
  model?: string
) =>
  useQuery({
    queryKey: ['diff', promptId, a, b, granularity, model],
    queryFn: () => apiClient.getPromptDiff(promptId, a, b, granularity, model),
    enabled: !!promptId && !!a && !!b,
  });

export const useChangelog = (promptId: string) =>
  useQuery({
    queryKey: ['changelog', promptId],
    queryFn: () => apiClient.getChangelog(promptId),
    enabled: !!promptId,
  });

export const usePromptAudit = (promptId: string) =>
  useQuery({
    queryKey: ['prompt-audit', promptId],
    queryFn: () => apiClient.getPromptAudit(promptId),
    enabled: !!promptId,
  });

export const useAuditVerification = () =>
  useQuery({ queryKey: ['audit-verify'], queryFn: () => apiClient.verifyAuditChain(), staleTime: 0 });

// Datasets
export const useDatasets = () => useQuery({ queryKey: ['datasets'], queryFn: () => apiClient.getDatasets() });
export const useDataset = (id: string) =>
  useQuery({ queryKey: ['dataset', id], queryFn: () => apiClient.getDataset(id), enabled: !!id });

export function useCreateDataset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; description?: string }) => apiClient.createDataset(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['datasets'] }),
  });
}

export function useAddCase() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { datasetId: string; input_text: string; expected_behavior: Record<string, unknown> }) =>
      apiClient.addCase(v.datasetId, { input_text: v.input_text, expected_behavior: v.expected_behavior }),
    onSuccess: (_d, v) => {
      qc.invalidateQueries({ queryKey: ['dataset', v.datasetId] });
      qc.invalidateQueries({ queryKey: ['datasets'] });
    },
  });
}

// Evaluations (poll while a run is PENDING/RUNNING)
export const useRubrics = () => useQuery({ queryKey: ['rubrics'], queryFn: () => apiClient.getRubrics() });

export const useRuns = () =>
  useQuery({
    queryKey: ['runs'],
    queryFn: () => apiClient.getRuns(),
    refetchInterval: (q) => (q.state.data?.some(isActive) ? 3000 : false),
  });

export const useRun = (id: string) =>
  useQuery({
    queryKey: ['run', id],
    queryFn: () => apiClient.getRun(id),
    enabled: !!id,
    refetchInterval: (q) => (isActive(q.state.data) ? 2000 : false),
  });

export function useCreateRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: EvaluationRunCreate) => apiClient.createRun(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['runs'] }),
  });
}

export function useCancelRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiClient.cancelRun(id),
    onSuccess: (_d, id) => {
      qc.invalidateQueries({ queryKey: ['runs'] });
      qc.invalidateQueries({ queryKey: ['run', id] });
    },
  });
}

export const useRunSummary = (id: string, active: boolean) =>
  useQuery({
    queryKey: ['run-summary', id],
    queryFn: () => apiClient.getRunSummary(id),
    enabled: !!id,
    refetchInterval: active ? 3000 : false,
  });

export const useRunCases = (id: string, active: boolean) =>
  useQuery({
    queryKey: ['run-cases', id],
    queryFn: () => apiClient.getRunCases(id),
    enabled: !!id,
    refetchInterval: active ? 3000 : false,
  });
