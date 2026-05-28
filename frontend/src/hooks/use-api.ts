import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/lib/api-client';
import type {
  Prompt,
  PromptCreate,
  PromptUpdate,
  PromptVersion,
  VersionCreate,
  EvaluationDataset,
  EvaluationRun,
  EvaluationRunCreate,
  ChangelogEntry,
  PromptStatistics,
} from '@/types/api';

// Prompts
export function usePrompts() {
  return useQuery({
    queryKey: ['prompts'],
    queryFn: () => apiClient.getPrompts(),
  });
}

export function usePrompt(id: string) {
  return useQuery({
    queryKey: ['prompt', id],
    queryFn: () => apiClient.getPrompt(id),
    enabled: !!id,
  });
}

export function useCreatePrompt() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: (data: PromptCreate) => apiClient.createPrompt(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['prompts'] });
    },
  });
}

export function useUpdatePrompt() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: PromptUpdate }) => 
      apiClient.updatePrompt(id, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['prompts'] });
      queryClient.invalidateQueries({ queryKey: ['prompt', variables.id] });
    },
  });
}

export function useDeletePrompt() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: (id: string) => apiClient.deletePrompt(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['prompts'] });
    },
  });
}

// Versions
export function useVersions(promptId: string) {
  return useQuery({
    queryKey: ['versions', promptId],
    queryFn: () => apiClient.getVersions(promptId),
    enabled: !!promptId,
  });
}

export function useVersion(id: string) {
  return useQuery({
    queryKey: ['version', id],
    queryFn: () => apiClient.getVersion(id),
    enabled: !!id,
  });
}

export function useCreateVersion() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: ({ promptId, data }: { promptId: string; data: VersionCreate }) => 
      apiClient.createVersion(promptId, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['versions', variables.promptId] });
      queryClient.invalidateQueries({ queryKey: ['prompt', variables.promptId] });
    },
  });
}

export function useActivateVersion() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: (versionId: string) => apiClient.activateVersion(versionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['versions'] });
      queryClient.invalidateQueries({ queryKey: ['prompts'] });
    },
  });
}

export function useRollbackPrompt() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: ({ promptId, versionId, semanticVersion }: { 
      promptId: string; 
      versionId?: string; 
      semanticVersion?: string 
    }) => apiClient.rollbackPrompt(promptId, versionId, semanticVersion),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['versions', variables.promptId] });
      queryClient.invalidateQueries({ queryKey: ['prompt', variables.promptId] });
    },
  });
}

// Datasets
export function useDatasets() {
  return useQuery({
    queryKey: ['datasets'],
    queryFn: () => apiClient.getDatasets(),
  });
}

export function useDataset(id: string) {
  return useQuery({
    queryKey: ['dataset', id],
    queryFn: () => apiClient.getDataset(id),
    enabled: !!id,
  });
}

export function useCreateDataset() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: (data: { name: string; description?: string }) => 
      apiClient.createDataset(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['datasets'] });
    },
  });
}

// Evaluations
export function useEvaluationRuns() {
  return useQuery({
    queryKey: ['evaluation-runs'],
    queryFn: () => apiClient.getEvaluationRuns(),
  });
}

export function useEvaluationRun(id: string) {
  return useQuery({
    queryKey: ['evaluation-run', id],
    queryFn: () => apiClient.getEvaluationRun(id),
    enabled: !!id,
  });
}

export function useCreateEvaluationRun() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: (data: EvaluationRunCreate) => apiClient.createEvaluationRun(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['evaluation-runs'] });
    },
  });
}

export function useEvaluationReport(id: string) {
  return useQuery({
    queryKey: ['evaluation-report', id],
    queryFn: () => apiClient.getEvaluationReport(id),
    enabled: !!id,
  });
}

export function useEvaluationHistory(promptId?: string) {
  return useQuery({
    queryKey: ['evaluation-history', promptId],
    queryFn: () => apiClient.getEvaluationHistory(promptId),
  });
}

// PromptOps
export function useChangelog(promptId: string, includeDiffs = true) {
  return useQuery({
    queryKey: ['changelog', promptId, includeDiffs],
    queryFn: () => apiClient.getChangelog(promptId, includeDiffs),
    enabled: !!promptId,
  });
}

export function useVersionDiff(versionAId: string, versionBId: string) {
  return useQuery({
    queryKey: ['version-diff', versionAId, versionBId],
    queryFn: () => apiClient.getVersionDiff(versionAId, versionBId),
    enabled: !!versionAId && !!versionBId,
  });
}

export function usePromptStatistics(promptId: string) {
  return useQuery({
    queryKey: ['prompt-statistics', promptId],
    queryFn: () => apiClient.getPromptStatistics(promptId),
    enabled: !!promptId,
  });
}

export function usePromptAuditHistory(promptId: string) {
  return useQuery({
    queryKey: ['prompt-audit-history', promptId],
    queryFn: () => apiClient.getPromptAuditHistory(promptId),
    enabled: !!promptId,
  });
}
