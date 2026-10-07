'use client';

import { useState } from 'react';
import { format } from 'date-fns';
import { FileText, Plus, Play, Undo2, ShieldCheck } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Empty, ErrorBox, Loading, Pill, inputClass } from '@/components/ui/bits';
import {
  useActivateVersion,
  useCreatePrompt,
  useCreateVersion,
  usePrompts,
  useRollbackPrompt,
  useVersionIntegrity,
  useVersions,
} from '@/hooks/use-api';

function IntegrityBadge({ promptId, versionId }: { promptId: string; versionId: string }) {
  const [checked, setChecked] = useState(false);
  const { data, isLoading, error } = useVersionIntegrity(promptId, versionId, checked);
  if (!checked)
    return (
      <Button variant="ghost" size="sm" onClick={() => setChecked(true)}>
        <ShieldCheck className="mr-1 h-3 w-3" /> Verify
      </Button>
    );
  if (isLoading) return <Loading label="" />;
  if (error) return <Pill tone="red">error</Pill>;
  return data?.intact ? <Pill tone="green">hash OK</Pill> : <Pill tone="red">TAMPERED</Pill>;
}

export default function PromptsPage() {
  const { data: prompts, isLoading, error } = usePrompts();
  const [selected, setSelected] = useState<string>('');
  const { data: versions, isLoading: versionsLoading, error: versionsError } = useVersions(selected);

  const createPrompt = useCreatePrompt();
  const createVersion = useCreateVersion();
  const activate = useActivateVersion();
  const rollback = useRollbackPrompt();

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [semver, setSemver] = useState('1.0.0');
  const [template, setTemplate] = useState('');
  const [temperature, setTemperature] = useState('');
  const [setActive, setSetActive] = useState(false);

  const active = versions?.find((v) => v.is_active);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Prompt Registry</h1>
        <p className="text-muted-foreground">
          Versions are immutable (enforced in the database). Publish a new version instead of editing one.
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Prompts</CardTitle>
            <CardDescription>Select a prompt</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {isLoading && <Loading />}
            <ErrorBox error={error} />
            {prompts?.length === 0 && <Empty>No prompts yet. Create one below.</Empty>}
            {prompts?.map((p) => (
              <button
                key={p.id}
                onClick={() => setSelected(p.id)}
                className={`w-full rounded-lg border p-3 text-left transition-colors ${
                  selected === p.id ? 'bg-primary text-primary-foreground' : 'hover:bg-accent'
                }`}
              >
                <div className="flex items-center gap-2 font-medium">
                  <FileText className="h-4 w-4" /> {p.name}
                </div>
                <div className="mt-1 text-xs opacity-80">
                  {p.version_count} version(s) · active: {p.active_version ?? 'none'}
                </div>
              </button>
            ))}
            <form
              className="space-y-2 border-t pt-3"
              onSubmit={(e) => {
                e.preventDefault();
                createPrompt.mutate(
                  { name, description: description || undefined },
                  { onSuccess: (p) => { setName(''); setDescription(''); setSelected(p.id); } }
                );
              }}
            >
              <div className="text-sm font-medium">New prompt</div>
              <input className={inputClass} placeholder="name" value={name} onChange={(e) => setName(e.target.value)} required />
              <input className={inputClass} placeholder="description (optional)" value={description} onChange={(e) => setDescription(e.target.value)} />
              <Button type="submit" size="sm" disabled={createPrompt.isPending}>
                <Plus className="mr-1 h-4 w-4" /> Create
              </Button>
              <ErrorBox error={createPrompt.error} />
            </form>
          </CardContent>
        </Card>

        <div className="space-y-6 md:col-span-2">
          {!selected ? (
            <Card>
              <CardContent className="pt-6">
                <Empty>Select a prompt to see its versions.</Empty>
              </CardContent>
            </Card>
          ) : (
            <>
              <Card>
                <CardHeader>
                  <CardTitle>Versions</CardTitle>
                  <CardDescription>Activation and rollback only change which version is active.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  {versionsLoading && <Loading />}
                  <ErrorBox error={versionsError || activate.error || rollback.error} />
                  {versions?.length === 0 && <Empty>No versions yet. Publish the first one below.</Empty>}
                  {versions && versions.length > 0 && (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Version</TableHead>
                          <TableHead>Status</TableHead>
                          <TableHead>Hash</TableHead>
                          <TableHead>Created</TableHead>
                          <TableHead>Actions</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {[...versions].reverse().map((v) => (
                          <TableRow key={v.id}>
                            <TableCell className="font-medium">{v.semantic_version}</TableCell>
                            <TableCell>{v.is_active ? <Pill tone="green">active</Pill> : <Pill>inactive</Pill>}</TableCell>
                            <TableCell className="font-mono text-xs" title={v.content_hash}>
                              {v.content_hash.slice(0, 10)}…
                            </TableCell>
                            <TableCell className="text-xs">{format(new Date(v.created_at), 'MMM d, yyyy HH:mm')}</TableCell>
                            <TableCell className="space-x-1">
                              {!v.is_active && (
                                <>
                                  <Button variant="ghost" size="sm" onClick={() => activate.mutate({ promptId: selected, versionId: v.id })}>
                                    <Play className="mr-1 h-3 w-3" /> Activate
                                  </Button>
                                  {active && (
                                    <Button variant="ghost" size="sm" onClick={() => rollback.mutate({ promptId: selected, versionId: v.id })}>
                                      <Undo2 className="mr-1 h-3 w-3" /> Roll back
                                    </Button>
                                  )}
                                </>
                              )}
                              <IntegrityBadge promptId={selected} versionId={v.id} />
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Publish a new version</CardTitle>
                  <CardDescription>Use {'{{input}}'} where the test input should be inserted.</CardDescription>
                </CardHeader>
                <CardContent>
                  <form
                    className="space-y-3"
                    onSubmit={(e) => {
                      e.preventDefault();
                      const provider_config: Record<string, unknown> = {};
                      if (temperature !== '') provider_config.temperature = Number(temperature);
                      createVersion.mutate(
                        { promptId: selected, data: { semantic_version: semver, template, provider_config, set_as_active: setActive } },
                        { onSuccess: () => setTemplate('') }
                      );
                    }}
                  >
                    <div className="grid grid-cols-3 gap-3">
                      <input className={inputClass} placeholder="1.0.0" pattern="\d+\.\d+\.\d+" value={semver} onChange={(e) => setSemver(e.target.value)} required />
                      <input className={inputClass} placeholder="temperature (optional)" type="number" step="0.1" min="0" max="2" value={temperature} onChange={(e) => setTemperature(e.target.value)} />
                      <label className="flex items-center gap-2 text-sm">
                        <input type="checkbox" checked={setActive} onChange={(e) => setSetActive(e.target.checked)} /> activate
                      </label>
                    </div>
                    <textarea className={`${inputClass} font-mono`} rows={6} placeholder="Answer concisely: {{input}}" value={template} onChange={(e) => setTemplate(e.target.value)} required />
                    <Button type="submit" disabled={createVersion.isPending}>
                      {createVersion.isPending ? 'Publishing…' : 'Publish version'}
                    </Button>
                    <ErrorBox error={createVersion.error} />
                  </form>
                </CardContent>
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
