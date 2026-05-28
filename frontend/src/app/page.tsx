'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { usePrompts, useEvaluationRuns } from '@/hooks/use-api';
import { FileText, PlayCircle, TrendingUp, Clock, DollarSign, Activity } from 'lucide-react';

export default function DashboardPage() {
  const { data: prompts, isLoading: promptsLoading } = usePrompts();
  const { data: evaluationRuns, isLoading: runsLoading } = useEvaluationRuns();

  const totalPrompts = prompts?.length || 0;
  const totalVersions = prompts?.reduce((acc, prompt) => acc + (prompt.versions?.length || 0), 0) || 0;
  const totalRuns = evaluationRuns?.length || 0;
  const completedRuns = evaluationRuns?.filter(run => run.status === 'COMPLETED').length || 0;
  const activeVersions = prompts?.filter(prompt => 
    prompt.versions?.some(v => v.is_active)
  ).length || 0;

  // Calculate average latency from completed runs
  const completedRunsWithResults = evaluationRuns?.filter(run => 
    run.status === 'COMPLETED' && run.results?.length > 0
  ) || [];
  
  const avgLatency = completedRunsWithResults.length > 0
    ? completedRunsWithResults.reduce((acc, run) => {
        const runLatency = run.results.reduce((sum, result) => sum + result.latency_ms, 0);
        return acc + (runLatency / run.results.length);
      }, 0) / completedRunsWithResults.length
    : 0;

  // Calculate total cost
  const totalCost = evaluationRuns?.reduce((acc, run) => {
    return acc + run.results.reduce((sum, result) => sum + result.estimated_cost, 0);
  }, 0) || 0;

  const stats = [
    {
      title: 'Total Prompts',
      value: totalPrompts,
      icon: FileText,
      description: 'Registered prompts',
    },
    {
      title: 'Active Versions',
      value: activeVersions,
      icon: Activity,
      description: 'Currently active versions',
    },
    {
      title: 'Total Versions',
      value: totalVersions,
      icon: TrendingUp,
      description: 'All prompt versions',
    },
    {
      title: 'Evaluation Runs',
      value: totalRuns,
      icon: PlayCircle,
      description: 'Total evaluation runs',
    },
    {
      title: 'Avg Latency',
      value: `${avgLatency.toFixed(0)}ms`,
      icon: Clock,
      description: 'Average response time',
    },
    {
      title: 'Total Cost',
      value: `$${totalCost.toFixed(4)}`,
      icon: DollarSign,
      description: 'Total evaluation cost',
    },
  ];

  const recentRuns = evaluationRuns?.slice(0, 5) || [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground">
          Overview of your prompt operations and evaluation metrics
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {stats.map((stat) => (
          <Card key={stat.title}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">
                {stat.title}
              </CardTitle>
              <stat.icon className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stat.value}</div>
              <p className="text-xs text-muted-foreground">
                {stat.description}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Recent Evaluation Runs</CardTitle>
            <CardDescription>
              Latest evaluation runs and their status
            </CardDescription>
          </CardHeader>
          <CardContent>
            {runsLoading ? (
              <div className="text-sm text-muted-foreground">Loading...</div>
            ) : recentRuns.length === 0 ? (
              <div className="text-sm text-muted-foreground">No evaluation runs yet</div>
            ) : (
              <div className="space-y-4">
                {recentRuns.map((run) => (
                  <div key={run.id} className="flex items-center justify-between">
                    <div className="space-y-1">
                      <p className="text-sm font-medium leading-none">
                        {run.provider} - {run.model}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {new Date(run.created_at).toLocaleDateString()}
                      </p>
                    </div>
                    <div className={`text-xs font-medium ${
                      run.status === 'COMPLETED' ? 'text-green-600' :
                      run.status === 'FAILED' ? 'text-red-600' :
                      'text-yellow-600'
                    }`}>
                      {run.status}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Prompt Overview</CardTitle>
            <CardDescription>
              Summary of your prompt registry
            </CardDescription>
          </CardHeader>
          <CardContent>
            {promptsLoading ? (
              <div className="text-sm text-muted-foreground">Loading...</div>
            ) : !prompts || prompts.length === 0 ? (
              <div className="text-sm text-muted-foreground">No prompts registered yet</div>
            ) : (
              <div className="space-y-4">
                {prompts.slice(0, 5).map((prompt) => (
                  <div key={prompt.id} className="flex items-center justify-between">
                    <div className="space-y-1">
                      <p className="text-sm font-medium leading-none">
                        {prompt.name}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {prompt.versions?.length || 0} versions
                      </p>
                    </div>
                    <div className="flex gap-1">
                      {prompt.tags?.slice(0, 2).map((tag) => (
                        <span
                          key={tag}
                          className="text-xs bg-secondary px-2 py-1 rounded"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
