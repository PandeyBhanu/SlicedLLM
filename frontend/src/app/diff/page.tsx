'use client';

import { useState } from 'react';
import { GitCompare } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { DiffView } from '@/components/diff-view';
import { Empty, ErrorBox, Loading, Pill, inputClass } from '@/components/ui/bits';
import { usePromptDiff, usePrompts, useVersions } from '@/hooks/use-api';
import type { Granularity } from '@/types/api';

export default function DiffPage() {
  const { data: prompts } = usePrompts();
  const [promptId, setPromptId] = useState('');
  const [a, setA] = useState('');
  const [b, setB] = useState('');
  const [granularity, setGranularity] = useState<Granularity>('token');
  const [model, setModel] = useState('');
  const { data: versions } = useVersions(promptId);
  const { data: diff, isLoading, error } = usePromptDiff(promptId, a, b, granularity, model || undefined);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Prompt Diff</h1>
        <p className="text-muted-foreground">
          Model-token diff between two immutable versions (insertions green, deletions red).
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <GitCompare className="h-5 w-5" /> Compare
          </CardTitle>
          <CardDescription>Pick a prompt, two versions, and how to split the text.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-5">
          <select className={inputClass} value={promptId} onChange={(e) => { setPromptId(e.target.value); setA(''); setB(''); }}>
            <option value="">Prompt…</option>
            {prompts?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <select className={inputClass} value={a} onChange={(e) => setA(e.target.value)} disabled={!promptId}>
            <option value="">Version A (original)…</option>
            {versions?.map((v) => <option key={v.id} value={v.id}>{v.semantic_version}</option>)}
          </select>
          <select className={inputClass} value={b} onChange={(e) => setB(e.target.value)} disabled={!promptId}>
            <option value="">Version B (modified)…</option>
            {versions?.map((v) => <option key={v.id} value={v.id}>{v.semantic_version}</option>)}
          </select>
          <select className={inputClass} value={granularity} onChange={(e) => setGranularity(e.target.value as Granularity)}>
            <option value="token">Model tokens (BPE)</option>
            <option value="line">Lines</option>
            <option value="char">Characters</option>
          </select>
          <input className={inputClass} placeholder="model for tokenizer (e.g. gpt-4o)" value={model} onChange={(e) => setModel(e.target.value)} disabled={granularity !== 'token'} />
        </CardContent>
      </Card>

      {!a || !b ? (
        <Empty>Select two versions to see the diff.</Empty>
      ) : (
        <>
          {isLoading && <Loading />}
          <ErrorBox error={error} />
          {diff && (
            <>
              <Card>
                <CardHeader>
                  <CardTitle>
                    {diff.version_a.semantic_version} → {diff.version_b.semantic_version}
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <DiffView diff={diff.template_diff} />
                  <div className="flex flex-wrap gap-2 text-xs">
                    {diff.variables.added.map((v) => <Pill key={`a${v}`} tone="green">+ {`{{${v}}}`}</Pill>)}
                    {diff.variables.removed.map((v) => <Pill key={`r${v}`} tone="red">- {`{{${v}}}`}</Pill>)}
                  </div>
                  {Object.keys(diff.config_diff).length > 0 && (
                    <div className="text-sm">
                      <div className="font-medium">Generation config changes</div>
                      <pre className="mt-1 rounded bg-muted p-2 text-xs">{JSON.stringify(diff.config_diff, null, 2)}</pre>
                    </div>
                  )}
                </CardContent>
              </Card>
            </>
          )}
        </>
      )}
    </div>
  );
}
