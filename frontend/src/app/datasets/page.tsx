'use client';

import { useState } from 'react';
import { Database, Plus } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Empty, ErrorBox, Loading, inputClass } from '@/components/ui/bits';
import { useAddCase, useCreateDataset, useDataset, useDatasets } from '@/hooks/use-api';

export default function DatasetsPage() {
  const { data: datasets, isLoading, error } = useDatasets();
  const [selected, setSelected] = useState('');
  const { data: dataset, isLoading: datasetLoading } = useDataset(selected);
  const createDataset = useCreateDataset();
  const addCase = useAddCase();

  const [name, setName] = useState('');
  const [input, setInput] = useState('');
  const [expected, setExpected] = useState('');

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Datasets</h1>
        <p className="text-muted-foreground">Test inputs shared by prompt A and prompt B in every run.</p>
      </div>
      <div className="grid gap-6 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Database className="h-5 w-5" /> Datasets</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {isLoading && <Loading />}
            <ErrorBox error={error} />
            {datasets?.length === 0 && <Empty>No datasets yet.</Empty>}
            {datasets?.map((d) => (
              <button
                key={d.id}
                onClick={() => setSelected(d.id)}
                className={`w-full rounded-lg border p-3 text-left ${selected === d.id ? 'bg-primary text-primary-foreground' : 'hover:bg-accent'}`}
              >
                <div className="font-medium">{d.name}</div>
                <div className="text-xs opacity-80">{d.case_count} case(s)</div>
              </button>
            ))}
            <form
              className="space-y-2 border-t pt-3"
              onSubmit={(e) => {
                e.preventDefault();
                createDataset.mutate({ name }, { onSuccess: (d) => { setName(''); setSelected(d.id); } });
              }}
            >
              <input className={inputClass} placeholder="new dataset name" value={name} onChange={(e) => setName(e.target.value)} required />
              <Button type="submit" size="sm" disabled={createDataset.isPending}><Plus className="mr-1 h-4 w-4" /> Create</Button>
              <ErrorBox error={createDataset.error} />
            </form>
          </CardContent>
        </Card>

        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle>{dataset?.name ?? 'Cases'}</CardTitle>
            <CardDescription>Each case is one input plus notes that tell the judge what a good answer looks like.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {!selected && <Empty>Select a dataset.</Empty>}
            {selected && datasetLoading && <Loading />}
            {dataset?.cases.length === 0 && <Empty>No cases yet.</Empty>}
            {dataset?.cases.map((c) => (
              <div key={c.id} className="rounded border p-3 text-sm">
                <div className="text-xs text-muted-foreground">#{c.ordinal + 1}</div>
                <div className="whitespace-pre-wrap">{c.input_text}</div>
                {Object.keys(c.expected_behavior).length > 0 && (
                  <pre className="mt-2 rounded bg-muted p-2 text-xs">{JSON.stringify(c.expected_behavior, null, 2)}</pre>
                )}
              </div>
            ))}
            {selected && (
              <form
                className="space-y-2 border-t pt-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  addCase.mutate(
                    {
                      datasetId: selected,
                      input_text: input,
                      expected_behavior: expected.trim() ? { expected: expected.trim() } : {},
                    },
                    { onSuccess: () => { setInput(''); setExpected(''); } }
                  );
                }}
              >
                <div className="text-sm font-medium">Add case</div>
                <textarea className={inputClass} rows={3} placeholder="Test input" value={input} onChange={(e) => setInput(e.target.value)} required />
                <textarea className={inputClass} rows={2} placeholder="Expected behavior / reference answer (optional)" value={expected} onChange={(e) => setExpected(e.target.value)} />
                <Button type="submit" size="sm" disabled={addCase.isPending}>Add case</Button>
                <ErrorBox error={addCase.error} />
              </form>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
