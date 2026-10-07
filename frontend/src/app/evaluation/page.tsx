'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Play } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Empty, ErrorBox, inputClass } from '@/components/ui/bits';
import { useCreateRun, useDatasets, usePrompts, useRubrics, useVersions } from '@/hooks/use-api';

const PROVIDERS = ['ollama', 'groq']; // the providers registered in app/providers/factory.py

function VersionPicker({
  label, promptId, versionId, onPrompt, onVersion,
}: {
  label: string; promptId: string; versionId: string;
  onPrompt: (id: string) => void; onVersion: (id: string) => void;
}) {
  const { data: prompts } = usePrompts();
  const { data: versions } = useVersions(promptId);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{label}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <select className={inputClass} value={promptId} onChange={(e) => { onPrompt(e.target.value); onVersion(''); }}>
          <option value="">Prompt…</option>
          {prompts?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <select className={inputClass} value={versionId} onChange={(e) => onVersion(e.target.value)} disabled={!promptId}>
          <option value="">Version…</option>
          {versions?.map((v) => (
            <option key={v.id} value={v.id}>{v.semantic_version}{v.is_active ? ' (active)' : ''}</option>
          ))}
        </select>
        {versionId && (
          <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded bg-muted p-2 text-xs">
            {versions?.find((v) => v.id === versionId)?.template}
          </pre>
        )}
      </CardContent>
    </Card>
  );
}

export default function EvaluationPage() {
  const router = useRouter();
  const { data: datasets } = useDatasets();
  const { data: rubrics } = useRubrics();
  const createRun = useCreateRun();

  const [promptA, setPromptA] = useState('');
  const [versionA, setVersionA] = useState('');
  const [promptB, setPromptB] = useState('');
  const [versionB, setVersionB] = useState('');
  const [datasetId, setDatasetId] = useState('');
  const [provider, setProvider] = useState('ollama');
  const [model, setModel] = useState('');
  const [judgeProvider, setJudgeProvider] = useState('');
  const [judgeModel, setJudgeModel] = useState('');
  const [rubricId, setRubricId] = useState('');
  const [strategy, setStrategy] = useState<'both' | 'alternate' | 'none'>('both');
  const [caseConcurrency, setCaseConcurrency] = useState('');
  const [maxRetries, setMaxRetries] = useState('');

  const dataset = datasets?.find((d) => d.id === datasetId);
  const ready = datasetId && versionA && versionB && model.trim();

  const submit = () => {
    createRun.mutate(
      {
        dataset_id: datasetId,
        prompt_version_a_id: versionA,
        prompt_version_b_id: versionB,
        provider,
        model: model.trim(),
        judge_provider: judgeProvider || undefined,
        judge_model: judgeModel.trim() || undefined,
        rubric_id: rubricId || undefined,
        settings: {
          judge_position_strategy: strategy,
          case_concurrency: caseConcurrency ? Number(caseConcurrency) : undefined,
          max_retries: maxRetries ? Number(maxRetries) : undefined,
        },
      },
      { onSuccess: (run) => router.push(`/results?run=${run.id}`) }
    );
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">New A/B Evaluation</h1>
        <p className="text-muted-foreground">
          Both versions answer every case with the same model; an LLM judge scores the two outputs against a rubric.
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <VersionPicker label="Prompt A" promptId={promptA} versionId={versionA} onPrompt={setPromptA} onVersion={setVersionA} />
        <VersionPicker label="Prompt B" promptId={promptB} versionId={versionB} onPrompt={setPromptB} onVersion={setVersionB} />
      </div>

      <div className="grid gap-6 md:grid-cols-3">
        <Card>
          <CardHeader><CardTitle>Dataset</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            <select className={inputClass} value={datasetId} onChange={(e) => setDatasetId(e.target.value)}>
              <option value="">Dataset…</option>
              {datasets?.map((d) => <option key={d.id} value={d.id}>{d.name} ({d.case_count})</option>)}
            </select>
            {datasets?.length === 0 && <Empty>Create a dataset on the Datasets page first.</Empty>}
            {dataset && dataset.case_count === 0 && <Empty>This dataset has no cases.</Empty>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Generation model</CardTitle><CardDescription>Used for A and B</CardDescription></CardHeader>
          <CardContent className="space-y-2">
            <select className={inputClass} value={provider} onChange={(e) => setProvider(e.target.value)}>
              {PROVIDERS.map((p) => <option key={p}>{p}</option>)}
            </select>
            <input className={inputClass} placeholder="model, e.g. llama3-8b-8192" value={model} onChange={(e) => setModel(e.target.value)} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Judge</CardTitle><CardDescription>Blank = same as generation model</CardDescription></CardHeader>
          <CardContent className="space-y-2">
            <select className={inputClass} value={judgeProvider} onChange={(e) => setJudgeProvider(e.target.value)}>
              <option value="">same provider</option>
              {PROVIDERS.map((p) => <option key={p}>{p}</option>)}
            </select>
            <input className={inputClass} placeholder="judge model" value={judgeModel} onChange={(e) => setJudgeModel(e.target.value)} />
            <select className={inputClass} value={rubricId} onChange={(e) => setRubricId(e.target.value)}>
              <option value="">default rubric</option>
              {rubrics?.map((r) => <option key={r.id} value={r.id}>{r.name} v{r.version}</option>)}
            </select>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle>Execution settings</CardTitle><CardDescription>Stored on the run so it can be reproduced.</CardDescription></CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-3">
          <label className="text-sm">
            Judge position strategy
            <select className={inputClass} value={strategy} onChange={(e) => setStrategy(e.target.value as typeof strategy)}>
              <option value="both">both orders (2 judge calls / case)</option>
              <option value="alternate">alternate (1 call, order varies by case)</option>
              <option value="none">none (no bias mitigation)</option>
            </select>
          </label>
          <label className="text-sm">
            Cases in parallel
            <input className={inputClass} type="number" min={1} max={64} placeholder="server default" value={caseConcurrency} onChange={(e) => setCaseConcurrency(e.target.value)} />
          </label>
          <label className="text-sm">
            Max retries per call
            <input className={inputClass} type="number" min={0} max={8} placeholder="server default" value={maxRetries} onChange={(e) => setMaxRetries(e.target.value)} />
          </label>
        </CardContent>
      </Card>

      <ErrorBox error={createRun.error} />
      <Button size="lg" className="w-full" disabled={!ready || createRun.isPending} onClick={submit}>
        <Play className="mr-2 h-4 w-4" /> {createRun.isPending ? 'Queueing…' : 'Start evaluation'}
      </Button>
    </div>
  );
}
