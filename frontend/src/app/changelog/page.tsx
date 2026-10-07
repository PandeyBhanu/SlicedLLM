'use client';

import { useState } from 'react';
import { format } from 'date-fns';
import { GitCommit, ShieldAlert, ShieldCheck } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Empty, ErrorBox, Loading, Pill } from '@/components/ui/bits';
import { useAuditVerification, useChangelog, usePromptAudit, usePrompts } from '@/hooks/use-api';

const ACTION_TONE: Record<string, 'green' | 'blue' | 'red' | 'gray'> = {
  CREATE: 'green', ACTIVATE: 'blue', ROLLBACK: 'red', UPDATE: 'gray', CANCEL: 'gray',
};

function ChainStatus() {
  const { data, isFetching, error, refetch } = useAuditVerification();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {data?.valid === false ? <ShieldAlert className="h-5 w-5 text-red-600" /> : <ShieldCheck className="h-5 w-5 text-green-600" />}
          Audit chain integrity
        </CardTitle>
        <CardDescription>
          Recomputes every event hash and link. Detects modified, deleted and reordered events (not truncation of the newest events).
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {isFetching && <Loading label="Verifying…" />}
        <ErrorBox error={error} />
        {data && (
          <div className="text-sm">
            {data.valid ? (
              <span className="text-green-700">Valid · {data.events_checked} event(s) · head #{data.head_seq ?? '—'}</span>
            ) : (
              <div className="space-y-1 text-red-700">
                <div>TAMPERING DETECTED · {data.errors.length} problem(s)</div>
                {data.errors.slice(0, 10).map((e, i) => <div key={i} className="font-mono text-xs">#{e.seq} {e.kind}: {e.detail}</div>)}
              </div>
            )}
          </div>
        )}
        <Button variant="outline" size="sm" onClick={() => refetch()}>Re-verify</Button>
      </CardContent>
    </Card>
  );
}

export default function ChangelogPage() {
  const { data: prompts } = usePrompts();
  const [promptId, setPromptId] = useState('');
  const { data: changelog, isLoading, error } = useChangelog(promptId);
  const { data: audit, isLoading: auditLoading, error: auditError } = usePromptAudit(promptId);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Changelog & Audit</h1>
        <p className="text-muted-foreground">Version history with token-level change sizes, and the hash-chained audit trail.</p>
      </div>

      <ChainStatus />

      <div className="grid gap-6 md:grid-cols-3">
        <Card>
          <CardHeader><CardTitle>Prompt</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {prompts?.length === 0 && <Empty>No prompts yet.</Empty>}
            {prompts?.map((p) => (
              <button key={p.id} onClick={() => setPromptId(p.id)}
                className={`w-full rounded-lg border p-3 text-left ${promptId === p.id ? 'bg-primary text-primary-foreground' : 'hover:bg-accent'}`}>
                {p.name}
              </button>
            ))}
          </CardContent>
        </Card>

        <div className="space-y-6 md:col-span-2">
          {!promptId ? <Empty>Select a prompt.</Empty> : (
            <>
              <Card>
                <CardHeader><CardTitle>Version changelog</CardTitle></CardHeader>
                <CardContent className="space-y-3">
                  {isLoading && <Loading />}
                  <ErrorBox error={error} />
                  {changelog?.length === 0 && <Empty>No versions yet.</Empty>}
                  {changelog?.map((e) => (
                    <div key={e.version_id} className="flex gap-3 border-b pb-3 last:border-0">
                      <GitCommit className="mt-1 h-4 w-4" />
                      <div className="text-sm">
                        <div className="flex items-center gap-2 font-medium">
                          {e.semantic_version} {e.is_active && <Pill tone="green">active</Pill>}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {format(new Date(e.created_at), 'MMM d, yyyy HH:mm')} · hash {e.content_hash.slice(0, 10)}…
                        </div>
                        {e.diff_stats ? (
                          <div className="mt-1 flex flex-wrap gap-2 text-xs">
                            <span>vs {e.previous_version}:</span>
                            <Pill tone="green">+{e.diff_stats.added} tokens</Pill>
                            <Pill tone="red">-{e.diff_stats.removed} tokens</Pill>
                            <Pill>{(e.diff_stats.similarity * 100).toFixed(0)}% similar</Pill>
                            <Pill>{e.tokenizer}</Pill>
                          </div>
                        ) : <div className="text-xs text-muted-foreground">first version</div>}
                      </div>
                    </div>
                  ))}
                </CardContent>
              </Card>

              <Card>
                <CardHeader><CardTitle>Audit events</CardTitle><CardDescription>Newest first. Append-only; each row links to the previous hash.</CardDescription></CardHeader>
                <CardContent className="space-y-3">
                  {auditLoading && <Loading />}
                  <ErrorBox error={auditError} />
                  {audit?.length === 0 && <Empty>No audit events.</Empty>}
                  {audit?.map((ev) => (
                    <details key={ev.id} className="rounded border p-2 text-sm">
                      <summary className="flex cursor-pointer flex-wrap items-center gap-2">
                        <span className="font-mono text-xs text-muted-foreground">#{ev.seq}</span>
                        <Pill tone={ACTION_TONE[ev.action] ?? 'gray'}>{ev.action}</Pill>
                        <span>{ev.entity_type}</span>
                        <span className="text-xs text-muted-foreground">
                          by {ev.actor_id} · {format(new Date(ev.occurred_at), 'MMM d HH:mm:ss')}
                        </span>
                      </summary>
                      <div className="mt-2 space-y-2 text-xs">
                        <div className="font-mono break-all">hash {ev.event_hash}<br />prev {ev.prev_hash}</div>
                        {ev.request_id && <div>request {ev.request_id}</div>}
                        {ev.before_state && <pre className="overflow-auto rounded bg-red-500/10 p-2">{JSON.stringify(ev.before_state, null, 2)}</pre>}
                        {ev.after_state && <pre className="overflow-auto rounded bg-green-500/10 p-2">{JSON.stringify(ev.after_state, null, 2)}</pre>}
                      </div>
                    </details>
                  ))}
                </CardContent>
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
