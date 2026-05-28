'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useEvaluationRuns, useEvaluationReport } from '@/hooks/use-api';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LineChart, Line } from 'recharts';
import { CheckCircle, XCircle, Clock, DollarSign, TrendingUp } from 'lucide-react';
import { useState } from 'react';

export default function ResultsPage() {
  const { data: evaluationRuns } = useEvaluationRuns();
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const { data: report } = useEvaluationReport(selectedRun || '');

  const selectedRunData = evaluationRuns?.find(run => run.id === selectedRun);

  // Prepare chart data
  const latencyData = selectedRunData?.results?.map((result, index) => ({
    name: `Case ${index + 1}`,
    latency: result.latency_ms,
  })) || [];

  const costData = selectedRunData?.results?.map((result, index) => ({
    name: `Case ${index + 1}`,
    cost: result.estimated_cost,
  })) || [];

  const confidenceData = selectedRunData?.results?.map((result, index) => ({
    name: `Case ${index + 1}`,
    confidence: result.confidence_score,
  })) || [];

  const totalCost = selectedRunData?.results?.reduce((sum, result) => sum + result.estimated_cost, 0) || 0;
  const avgLatency = selectedRunData?.results?.length > 0
    ? selectedRunData.results.reduce((sum, result) => sum + result.latency_ms, 0) / selectedRunData.results.length
    : 0;
  const avgConfidence = selectedRunData?.results?.length > 0
    ? selectedRunData.results.reduce((sum, result) => sum + result.confidence_score, 0) / selectedRunData.results.length
    : 0;
  const passRate = selectedRunData?.results?.length > 0
    ? (selectedRunData.results.filter(r => r.winner === 'A' || r.winner === 'B').length / selectedRunData.results.length) * 100
    : 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Evaluation Results</h1>
        <p className="text-muted-foreground">
          View detailed results from your evaluation runs
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Pass Rate</CardTitle>
            <CheckCircle className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{passRate.toFixed(0)}%</div>
            <p className="text-xs text-muted-foreground">
              {selectedRunData?.results?.length || 0} cases evaluated
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Avg Latency</CardTitle>
            <Clock className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{avgLatency.toFixed(0)}ms</div>
            <p className="text-xs text-muted-foreground">
              Average response time
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Cost</CardTitle>
            <DollarSign className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">${totalCost.toFixed(4)}</div>
            <p className="text-xs text-muted-foreground">
              Total evaluation cost
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Avg Confidence</CardTitle>
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{(avgConfidence * 100).toFixed(0)}%</div>
            <p className="text-xs text-muted-foreground">
              Average confidence score
            </p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Evaluation Runs</CardTitle>
            <CardDescription>
              Select a run to view detailed results
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {evaluationRuns?.map((run) => (
                <button
                  key={run.id}
                  onClick={() => setSelectedRun(run.id)}
                  className={`w-full text-left p-3 rounded-lg border transition-colors ${
                    selectedRun === run.id
                      ? 'bg-primary text-primary-foreground'
                      : 'hover:bg-accent'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="font-medium">{run.provider} - {run.model}</div>
                      <div className="text-xs opacity-80 mt-1">
                        {new Date(run.created_at).toLocaleString()}
                      </div>
                    </div>
                    <div className={`text-xs font-medium ${
                      run.status === 'COMPLETED' ? 'text-green-600' :
                      run.status === 'FAILED' ? 'text-red-600' :
                      'text-yellow-600'
                    }`}>
                      {run.status}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </CardContent>
        </Card>

        {selectedRunData && (
          <Card>
            <CardHeader>
              <CardTitle>Run Details</CardTitle>
              <CardDescription>
                Configuration and status
              </CardDescription>
            </CardHeader>
          <CardContent>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Provider</span>
                <span className="font-medium">{selectedRunData.provider}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Model</span>
                <span className="font-medium">{selectedRunData.model}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Status</span>
                <span className={`font-medium ${
                  selectedRunData.status === 'COMPLETED' ? 'text-green-600' :
                  selectedRunData.status === 'FAILED' ? 'text-red-600' :
                  'text-yellow-600'
                }`}>
                  {selectedRunData.status}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Started</span>
                <span className="font-medium">
                  {selectedRunData.started_at ? new Date(selectedRunData.started_at).toLocaleString() : 'Not started'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Completed</span>
                <span className="font-medium">
                  {selectedRunData.completed_at ? new Date(selectedRunData.completed_at).toLocaleString() : 'In progress'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Results</span>
                <span className="font-medium">{selectedRunData.results?.length || 0} cases</span>
              </div>
            </div>
          </CardContent>
        </Card>
        )}
      </div>

      {selectedRunData && selectedRunData.results && selectedRunData.results.length > 0 && (
        <>
          <div className="grid gap-6 md:grid-cols-3">
            <Card>
              <CardHeader>
                <CardTitle>Latency Distribution</CardTitle>
                <CardDescription>Response time per case</CardDescription>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={latencyData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" />
                    <YAxis />
                    <Tooltip />
                    <Bar dataKey="latency" fill="#3b82f6" />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Cost Distribution</CardTitle>
                <CardDescription>Cost per case</CardDescription>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={costData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" />
                    <YAxis />
                    <Tooltip />
                    <Bar dataKey="cost" fill="#10b981" />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Confidence Scores</CardTitle>
                <CardDescription>Confidence per case</CardDescription>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={confidenceData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" />
                    <YAxis />
                    <Tooltip />
                    <Line type="monotone" dataKey="confidence" stroke="#8b5cf6" />
                  </LineChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Detailed Results</CardTitle>
              <CardDescription>
                Per-case evaluation results
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Case</TableHead>
                    <TableHead>Winner</TableHead>
                    <TableHead>Confidence</TableHead>
                    <TableHead>Latency</TableHead>
                    <TableHead>Cost</TableHead>
                    <TableHead>Reasoning</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {selectedRunData.results.map((result, index) => (
                    <TableRow key={result.id}>
                      <TableCell className="font-medium">Case {index + 1}</TableCell>
                      <TableCell>
                        {result.winner ? (
                          <span className={`flex items-center gap-1 ${
                            result.winner === 'A' ? 'text-green-600' : 'text-blue-600'
                          }`}>
                            <CheckCircle className="h-4 w-4" />
                            Version {result.winner}
                          </span>
                        ) : (
                          <span className="flex items-center gap-1 text-muted-foreground">
                            <XCircle className="h-4 w-4" />
                            Tie
                          </span>
                        )}
                      </TableCell>
                      <TableCell>{(result.confidence_score * 100).toFixed(0)}%</TableCell>
                      <TableCell>{result.latency_ms}ms</TableCell>
                      <TableCell>${result.estimated_cost.toFixed(6)}</TableCell>
                      <TableCell className="max-w-xs truncate">
                        {result.reasoning || 'N/A'}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
