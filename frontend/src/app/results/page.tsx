'use client';

import { Fragment, Suspense, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { format } from 'date-fns';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Ban } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import {
  Empty, ErrorBox, Loading, Pill, Stat, StatusBadge, fmtMs, fmtNum, fmtPct, fmtUsd,
} from '@/components/ui/bits';
import { useCancelRun, useRun, useRunCases, useRuns, useRunSummary } from '@/hooks/use-api';
import type { CaseResult, EvaluationRun, RunSummary } from '@/types/api';

const winnerTone = (w: string | null) => (w === 'A' ? 'green' : w === 'B' ? 'blue' : 'gray');

function RunProgress({ run }: { run: EvaluationRun }) {
  const p = run.progress;
  if (!p) return null;
  const done = p.completed_cases + p.failed_cases;
  const pct = p.total_cases ? (done / p.total_cases) * 100 : 0;
  return (
    <div className="space-y-1">
      <div className="h-2 w-full overflow-hidden rounded bg-muted">
        <div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} />
      </div>
      <div className="text-xs text-muted-foreground">
        {done}/{p.total_cases} cases finished · {p.failed_cases} failed
      </div>
    </div>
  );
}

function SummaryCards({ s, run }: { s: RunSummary; run: EvaluationRun }) {
  const decisive = s.wins_a + s.wins_b;
  return (
    <div className="grid gap-4 md:grid-cols-4">
      <Stat
        label={`Win rate A (${run.version_a_label})`}
        value={fmtPct(s.win_rate_a)}
        hint={`${s.wins_a} wins · ${s.ties} ties · ${s.wins_b} losses`}
      />
      <Stat label={`Win rate B (${run.version_b_label})`} value={fmtPct(s.win_rate_b)} hint={`of ${s.completed_cases} judged cases`} />
      <Stat
        label="A share of decisive cases"
        value={fmtPct(s.a_share_of_decisive)}
        hint={decisive ? `95% CI ${fmtPct(s.a_share_ci_low)} – ${fmtPct(s.a_share_ci_high)} (n=${decisive})` : 'no decisive cases'}
      />
      <Stat
        label="Judge confidence"
        value={fmtPct(s.avg_confidence)}
        hint={`position-consistent: ${fmtPct(s.position_consistency_rate)}`}
      />
      <Stat label="Avg score A" value={`${fmtNum(s.slot_a.avg_score)} / ${s.rubric_scale_max}`} />
      <Stat label="Avg score B" value={`${fmtNum(s.slot_b.avg_score)} / ${s.rubric_scale_max}`} />
      <Stat
        label="Latency A / B (avg)"
        value={`${fmtMs(s.slot_a.avg_latency_ms)} / ${fmtMs(s.slot_b.avg_latency_ms)}`}
        hint={`p95 ${fmtMs(s.slot_a.p95_latency_ms)} / ${fmtMs(s.slot_b.p95_latency_ms)}`}
      />
      <Stat
        label="Tokens A / B / judge"
        value={`${s.slot_a.total_tokens} / ${s.slot_b.total_tokens} / ${s.judge_tokens}`}
        hint={`cost ${fmtUsd(s.slot_a.estimated_cost)} / ${fmtUsd(s.slot_b.estimated_cost)} / ${fmtUsd(s.judge_cost)}`}
      />
    </div>
  );
}

function Charts({ s, cases }: { s: RunSummary; cases: CaseResult[] }) {
  const wins = [
    { name: `A (${s.wins_a})`, count: s.wins_a },
    { name: `Tie (${s.ties})`, count: s.ties },
    { name: `B (${s.wins_b})`, count: s.wins_b },
  ];
  const latency = cases.map((c) => ({
    name: `#${c.ordinal + 1}`,
    A: c.outputs.find((o) => o.slot === 'A')?.latency_ms ?? 0,
    B: c.outputs.find((o) => o.slot === 'B')?.latency_ms ?? 0,
  }));
  const chart = (title: string, data: object[], keys: { key: string; fill: string }[], x = 'name') => (
    <Card>
      <CardHeader><CardTitle className="text-base">{title}</CardTitle></CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey={x} />
            <YAxis />
            <Tooltip />
            {keys.length > 1 && <Legend />}
            {keys.map((k) => <Bar key={k.key} dataKey={k.key} fill={k.fill} />)}
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {chart('Case outcomes', wins, [{ key: 'count', fill: '#6366f1' }])}
      {s.criteria.length > 0 &&
        chart(
          `Mean rubric score per criterion (${s.rubric_scale_min}–${s.rubric_scale_max})`,
          s.criteria.map((c) => ({ name: c.criterion, A: +c.avg_score_a.toFixed(2), B: +c.avg_score_b.toFixed(2) })),
          [{ key: 'A', fill: '#22c55e' }, { key: 'B', fill: '#3b82f6' }]
        )}
      {latency.length > 0 && chart('Latency per case (ms)', latency, [{ key: 'A', fill: '#22c55e' }, { key: 'B', fill: '#3b82f6' }])}
    </div>
  );
}

function CaseDetail({ c, scaleMax }: { c: CaseResult; scaleMax: number }) {
  const [a, b] = ['A', 'B'].map((slot) => c.outputs.find((o) => o.slot === slot));
  const scores = c.judge_evaluations.find((j) => j.status === 'COMPLETED');
  return (
    <div className="space-y-4 rounded-lg border bg-muted/20 p-4">
      <div>
        <div className="text-xs font-medium text-muted-foreground">Input</div>
        <div className="whitespace-pre-wrap text-sm">{c.input_text}</div>
        {Object.keys(c.expected_behavior).length > 0 && (
          <pre className="mt-2 rounded bg-muted p-2 text-xs">{JSON.stringify(c.expected_behavior, null, 2)}</pre>
        )}
      </div>
      {c.error && <ErrorBox error={c.error} />}
      <div className="grid gap-4 md:grid-cols-2">
        {[['A', a], ['B', b]].map(([slot, o]) => {
          const out = o as CaseResult['outputs'][number] | undefined;
          return (
            <div key={slot as string} className="space-y-2 rounded border bg-background p-3">
              <div className="flex items-center justify-between">
                <span className="font-medium">Output {slot as string}</span>
                {out && <Pill tone={out.status === 'COMPLETED' ? 'green' : 'red'}>{out.status}</Pill>}
              </div>
              {out ? (
                <>
                  <pre className="max-h-64 overflow-auto whitespace-pre-wrap text-sm">{out.output_text ?? out.error}</pre>
                  <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                    <span>{fmtMs(out.latency_ms)}</span>
                    <span>{out.prompt_tokens}+{out.completion_tokens} tokens</span>
                    <span>{fmtUsd(out.estimated_cost)}</span>
                    <span>attempts: {out.attempts}</span>
                    <span>{out.provider}/{out.model}</span>
                  </div>
                  <details className="text-xs">
                    <summary className="cursor-pointer text-muted-foreground">Rendered prompt & parameters</summary>
                    <pre className="mt-1 whitespace-pre-wrap rounded bg-muted p-2">{out.rendered_prompt}</pre>
                    <pre className="mt-1 rounded bg-muted p-2">{JSON.stringify(out.generation_params)}</pre>
                  </details>
                </>
              ) : (
                <Empty>No output recorded.</Empty>
              )}
            </div>
          );
        })}
      </div>

      {scores && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-medium">Judge</span>
            <Pill tone={winnerTone(c.winner)}>winner: {c.winner}</Pill>
            <Pill>score A {fmtNum(c.score_a)} · B {fmtNum(c.score_b)} / {scaleMax}</Pill>
            <Pill>confidence {fmtPct(c.confidence)}</Pill>
            <Pill tone={c.position_consistent ? 'green' : 'red'}>
              {c.position_consistent ? 'consistent across orderings' : 'position-inconsistent'}
            </Pill>
            <span className="text-xs text-muted-foreground">
              {scores.judge_provider}/{scores.judge_model} · rubric v{scores.rubric_version}
            </span>
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Criterion</TableHead>
                <TableHead>A</TableHead>
                <TableHead>B</TableHead>
                <TableHead>Reason (judge)</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {scores.rubric_scores.map((r) => (
                <TableRow key={r.criterion}>
                  <TableCell>{r.criterion}</TableCell>
                  <TableCell className={r.score_a > r.score_b ? 'font-bold text-green-700' : ''}>{r.score_a}</TableCell>
                  <TableCell className={r.score_b > r.score_a ? 'font-bold text-blue-700' : ''}>{r.score_b}</TableCell>
                  <TableCell className="text-xs">{r.reason}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {scores.reasoning && <p className="text-sm italic">“{scores.reasoning}”</p>}
          <details className="text-xs">
            <summary className="cursor-pointer text-muted-foreground">Judge passes ({c.judge_evaluations.length})</summary>
            {c.judge_evaluations.map((j) => (
              <div key={j.id} className="mt-1 rounded bg-muted p-2">
                pass {j.pass_index} · {j.swapped ? 'swapped order' : 'original order'} · {j.status} · winner {j.winner ?? '—'} ·
                confidence {fmtPct(j.confidence)} · attempts {j.attempts}
                {j.error && <span className="text-red-700"> · {j.error}</span>}
              </div>
            ))}
          </details>
        </div>
      )}
      {!scores && c.judge_evaluations.some((j) => j.status === 'FAILED') && (
        <ErrorBox error={`Judge failed: ${c.judge_evaluations.map((j) => j.error).filter(Boolean).join(' | ')}`} />
      )}
    </div>
  );
}

function RunDetail({ runId }: { runId: string }) {
  const { data: run, isLoading, error } = useRun(runId);
  const active = run ? ['PENDING', 'RUNNING'].includes(run.status) : false;
  const { data: summary } = useRunSummary(runId, active);
  const { data: cases } = useRunCases(runId, active);
  const cancel = useCancelRun();
  const [openCase, setOpenCase] = useState<string>('');

  if (isLoading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!run) return null;
  const finished = (summary?.completed_cases ?? 0) > 0;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                {run.version_a_label} vs {run.version_b_label} <StatusBadge status={run.status} />
              </CardTitle>
              <CardDescription>
                {run.dataset_name} · {run.provider}/{run.model} · judge {run.judge_provider}/{run.judge_model} ·
                strategy {String(run.config.judge_position_strategy)} · started{' '}
                {run.started_at ? format(new Date(run.started_at), 'MMM d HH:mm:ss') : 'not started'}
              </CardDescription>
            </div>
            {active && (
              <Button variant="outline" size="sm" disabled={cancel.isPending || run.cancel_requested} onClick={() => cancel.mutate(run.id)}>
                <Ban className="mr-1 h-4 w-4" /> {run.cancel_requested ? 'Cancelling…' : 'Cancel'}
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <RunProgress run={run} />
          {run.status === 'PENDING' && <Empty>Queued - waiting for a worker to pick this run up.</Empty>}
          {run.error && <ErrorBox error={run.error} />}
          <ErrorBox error={cancel.error} />
        </CardContent>
      </Card>

      {summary && finished && (
        <>
          <SummaryCards s={summary} run={run} />
          <Charts s={summary} cases={cases ?? []} />
          <p className="text-xs text-muted-foreground">{summary.note}</p>
        </>
      )}
      {summary && !finished && !active && <Empty>No case produced a judged result for this run.</Empty>}

      <Card>
        <CardHeader><CardTitle>Cases</CardTitle><CardDescription>Click a row for side-by-side outputs and judge scores.</CardDescription></CardHeader>
        <CardContent>
          {!cases || cases.length === 0 ? (
            <Empty>{active ? 'Waiting for the first case to finish…' : 'No cases recorded.'}</Empty>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>#</TableHead>
                  <TableHead>Input</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Winner</TableHead>
                  <TableHead>Score A / B</TableHead>
                  <TableHead>Confidence</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {cases.map((c) => (
                  <Fragment key={c.result_id}>
                    <TableRow className="cursor-pointer" onClick={() => setOpenCase(openCase === c.result_id ? '' : c.result_id)}>
                      <TableCell>{c.ordinal + 1}</TableCell>
                      <TableCell className="max-w-xs truncate">{c.input_text}</TableCell>
                      <TableCell><StatusBadge status={c.status} /></TableCell>
                      <TableCell>{c.winner ? <Pill tone={winnerTone(c.winner)}>{c.winner}</Pill> : '—'}</TableCell>
                      <TableCell>{fmtNum(c.score_a)} / {fmtNum(c.score_b)}</TableCell>
                      <TableCell>{fmtPct(c.confidence)}</TableCell>
                    </TableRow>
                    {openCase === c.result_id && (
                      <TableRow key={`${c.result_id}-d`}>
                        <TableCell colSpan={6}>
                          <CaseDetail c={c} scaleMax={summary?.rubric_scale_max ?? 5} />
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function ResultsContent() {
  const router = useRouter();
  const params = useSearchParams();
  const selected = params.get('run') ?? '';
  const { data: runs, isLoading, error } = useRuns();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Evaluation Results</h1>
        <p className="text-muted-foreground">Every number here is read from persisted outputs and judge scores.</p>
      </div>
      <div className="grid gap-6 lg:grid-cols-4">
        <Card className="lg:col-span-1">
          <CardHeader><CardTitle>Runs</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {isLoading && <Loading />}
            <ErrorBox error={error} />
            {runs?.length === 0 && <Empty>No runs yet. Start one from “Evaluation”.</Empty>}
            {runs?.map((r) => (
              <button
                key={r.id}
                onClick={() => router.push(`/results?run=${r.id}`)}
                className={`w-full rounded-lg border p-3 text-left ${selected === r.id ? 'bg-primary text-primary-foreground' : 'hover:bg-accent'}`}
              >
                <div className="flex items-center justify-between text-sm font-medium">
                  <span>{r.version_a_label} vs {r.version_b_label}</span>
                  <StatusBadge status={r.status} />
                </div>
                <div className="mt-1 text-xs opacity-80">
                  {r.dataset_name} · {r.model} · {format(new Date(r.created_at), 'MMM d HH:mm')}
                </div>
                {r.progress && <div className="text-xs opacity-80">{r.progress.completed_cases + r.progress.failed_cases}/{r.progress.total_cases} cases</div>}
              </button>
            ))}
          </CardContent>
        </Card>
        <div className="lg:col-span-3">
          {selected ? <RunDetail runId={selected} /> : <Empty>Select a run.</Empty>}
        </div>
      </div>
    </div>
  );
}

export default function ResultsPage() {
  return (
    <Suspense fallback={<Loading />}>
      <ResultsContent />
    </Suspense>
  );
}
