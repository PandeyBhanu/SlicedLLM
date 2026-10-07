'use client';

import Link from 'next/link';
import { format } from 'date-fns';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, ErrorBox, Loading, Stat, StatusBadge } from '@/components/ui/bits';
import { useDatasets, usePrompts, useRuns } from '@/hooks/use-api';

export default function DashboardPage() {
  const prompts = usePrompts();
  const runs = useRuns();
  const datasets = useDatasets();

  const done = runs.data?.filter((r) => r.status === 'COMPLETED').length ?? 0;
  const active = runs.data?.filter((r) => r.status === 'RUNNING' || r.status === 'PENDING').length ?? 0;
  const versions = prompts.data?.reduce((n, p) => n + p.version_count, 0) ?? 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground">Counts come straight from the API; nothing is precomputed or mocked.</p>
      </div>
      <ErrorBox error={prompts.error || runs.error || datasets.error} />
      <div className="grid gap-4 md:grid-cols-5">
        <Stat label="Prompts" value={prompts.data?.length ?? '…'} />
        <Stat label="Prompt versions" value={prompts.data ? versions : '…'} />
        <Stat label="Datasets" value={datasets.data?.length ?? '…'} />
        <Stat label="Runs completed" value={runs.data ? done : '…'} />
        <Stat label="Runs in progress" value={runs.data ? active : '…'} />
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Recent runs</CardTitle><CardDescription>Latest A/B evaluations</CardDescription></CardHeader>
          <CardContent className="space-y-3">
            {runs.isLoading && <Loading />}
            {runs.data?.length === 0 && <Empty>No runs yet. <Link className="underline" href="/evaluation">Start one</Link>.</Empty>}
            {runs.data?.slice(0, 6).map((r) => (
              <Link key={r.id} href={`/results?run=${r.id}`} className="flex items-center justify-between rounded border p-3 hover:bg-accent">
                <div>
                  <div className="text-sm font-medium">{r.version_a_label} vs {r.version_b_label} · {r.dataset_name}</div>
                  <div className="text-xs text-muted-foreground">{r.model} · {format(new Date(r.created_at), 'MMM d HH:mm')}</div>
                </div>
                <StatusBadge status={r.status} />
              </Link>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Prompts</CardTitle><CardDescription>Active version per prompt</CardDescription></CardHeader>
          <CardContent className="space-y-3">
            {prompts.isLoading && <Loading />}
            {prompts.data?.length === 0 && <Empty>No prompts yet. <Link className="underline" href="/prompts">Create one</Link>.</Empty>}
            {prompts.data?.slice(0, 6).map((p) => (
              <div key={p.id} className="flex items-center justify-between rounded border p-3 text-sm">
                <span className="font-medium">{p.name}</span>
                <span className="text-xs text-muted-foreground">{p.version_count} version(s) · active {p.active_version ?? 'none'}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
