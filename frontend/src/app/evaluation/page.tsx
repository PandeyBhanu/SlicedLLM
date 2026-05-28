'use client';

import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { useDatasets, usePrompts, useVersions, useCreateEvaluationRun } from '@/hooks/use-api';
import { Play, Database, FileText, Settings, Loader2 } from 'lucide-react';

export default function EvaluationPage() {
  const { data: datasets } = useDatasets();
  const { data: prompts } = usePrompts();
  const createEvaluationRun = useCreateEvaluationRun();
  
  const [selectedDataset, setSelectedDataset] = useState<string | null>(null);
  const [selectedPrompt, setSelectedPrompt] = useState<string | null>(null);
  const [selectedVersionA, setSelectedVersionA] = useState<string | null>(null);
  const [selectedVersionB, setSelectedVersionB] = useState<string | null>(null);
  const [selectedProvider, setSelectedProvider] = useState('ollama');
  const [selectedModel, setSelectedModel] = useState('llama3');
  const [isRunning, setIsRunning] = useState(false);

  const { data: versions } = useVersions(selectedPrompt || '');

  const handleRunEvaluation = () => {
    if (!selectedDataset || !selectedVersionA) {
      alert('Please select a dataset and at least one version');
      return;
    }

    setIsRunning(true);
    createEvaluationRun.mutate(
      {
        dataset_id: selectedDataset,
        prompt_version_a_id: selectedVersionA,
        prompt_version_b_id: selectedVersionB || undefined,
        provider: selectedProvider,
        model: selectedModel,
      },
      {
        onSuccess: () => {
          setIsRunning(false);
          alert('Evaluation run started successfully!');
        },
        onError: () => {
          setIsRunning(false);
          alert('Failed to start evaluation run');
        },
      }
    );
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Evaluation Runner</h1>
        <p className="text-muted-foreground">
          Run evaluations on your prompts with different datasets and providers
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Database className="h-5 w-5" />
              Dataset
            </CardTitle>
            <CardDescription>Select evaluation dataset</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {datasets?.map((dataset) => (
                <button
                  key={dataset.id}
                  onClick={() => setSelectedDataset(dataset.id)}
                  className={`w-full text-left p-3 rounded-lg border transition-colors ${
                    selectedDataset === dataset.id
                      ? 'bg-primary text-primary-foreground'
                      : 'hover:bg-accent'
                  }`}
                >
                  <div className="font-medium">{dataset.name}</div>
                  {dataset.description && (
                    <div className="text-xs opacity-80 mt-1">{dataset.description}</div>
                  )}
                  <div className="text-xs opacity-80 mt-1">
                    {dataset.cases?.length || 0} cases
                  </div>
                </button>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileText className="h-5 w-5" />
              Prompt
            </CardTitle>
            <CardDescription>Select prompt to evaluate</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {prompts?.map((prompt) => (
                <button
                  key={prompt.id}
                  onClick={() => {
                    setSelectedPrompt(prompt.id);
                    setSelectedVersionA(null);
                    setSelectedVersionB(null);
                  }}
                  className={`w-full text-left p-3 rounded-lg border transition-colors ${
                    selectedPrompt === prompt.id
                      ? 'bg-primary text-primary-foreground'
                      : 'hover:bg-accent'
                  }`}
                >
                  <div className="font-medium">{prompt.name}</div>
                  {prompt.description && (
                    <div className="text-xs opacity-80 mt-1">{prompt.description}</div>
                  )}
                </button>
              ))}
            </div>
          </CardContent>
        </Card>

        {selectedPrompt && (
          <Card>
            <CardHeader>
              <CardTitle>Versions</CardTitle>
              <CardDescription>Select versions to compare</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {versions?.map((version) => (
                  <div key={version.id} className="space-y-1">
                    <button
                      onClick={() => setSelectedVersionA(version.id)}
                      className={`w-full text-left p-2 rounded border transition-colors text-sm ${
                        selectedVersionA === version.id
                          ? 'bg-green-500/20 border-green-500'
                          : 'hover:bg-accent'
                      }`}
                    >
                      <span className="font-medium">A: {version.semantic_version}</span>
                      {version.is_active && (
                        <span className="ml-2 text-xs bg-green-500 px-2 py-0.5 rounded text-white">
                          Active
                        </span>
                      )}
                    </button>
                    <button
                      onClick={() => setSelectedVersionB(version.id)}
                      className={`w-full text-left p-2 rounded border transition-colors text-sm ${
                        selectedVersionB === version.id
                          ? 'bg-blue-500/20 border-blue-500'
                          : 'hover:bg-accent'
                      }`}
                    >
                      <span className="font-medium">B: {version.semantic_version}</span>
                      {version.is_active && (
                        <span className="ml-2 text-xs bg-green-500 px-2 py-0.5 rounded text-white">
                          Active
                        </span>
                      )}
                    </button>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Settings className="h-5 w-5" />
              Provider
            </CardTitle>
            <CardDescription>Configure provider settings</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div>
                <label className="text-sm font-medium">Provider</label>
                <select
                  value={selectedProvider}
                  onChange={(e) => setSelectedProvider(e.target.value)}
                  className="w-full mt-1 px-3 py-2 border rounded-md"
                >
                  <option value="ollama">Ollama</option>
                  <option value="groq">Groq</option>
                  <option value="openai">OpenAI</option>
                </select>
              </div>
              <div>
                <label className="text-sm font-medium">Model</label>
                <select
                  value={selectedModel}
                  onChange={(e) => setSelectedModel(e.target.value)}
                  className="w-full mt-1 px-3 py-2 border rounded-md"
                >
                  {selectedProvider === 'ollama' && (
                    <>
                      <option value="llama3">llama3</option>
                      <option value="llama2">llama2</option>
                      <option value="mistral">mistral</option>
                    </>
                  )}
                  {selectedProvider === 'groq' && (
                    <>
                      <option value="llama3-8b-8192">llama3-8b-8192</option>
                      <option value="mixtral-8x7b-32768">mixtral-8x7b-32768</option>
                      <option value="gemma-7b-it">gemma-7b-it</option>
                    </>
                  )}
                  {selectedProvider === 'openai' && (
                    <>
                      <option value="gpt-4">gpt-4</option>
                      <option value="gpt-3.5-turbo">gpt-3.5-turbo</option>
                      <option value="gpt-4-turbo">gpt-4-turbo</option>
                    </>
                  )}
                </select>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Evaluation Summary</CardTitle>
          <CardDescription>
            Review your configuration before running
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4 text-sm">
            <div>
              <div className="text-muted-foreground">Dataset</div>
              <div className="font-medium">
                {datasets?.find(d => d.id === selectedDataset)?.name || 'Not selected'}
              </div>
            </div>
            <div>
              <div className="text-muted-foreground">Version A</div>
              <div className="font-medium">
                {versions?.find(v => v.id === selectedVersionA)?.semantic_version || 'Not selected'}
              </div>
            </div>
            <div>
              <div className="text-muted-foreground">Version B</div>
              <div className="font-medium">
                {versions?.find(v => v.id === selectedVersionB)?.semantic_version || 'Not selected'}
              </div>
            </div>
            <div>
              <div className="text-muted-foreground">Provider</div>
              <div className="font-medium">
                {selectedProvider} - {selectedModel}
              </div>
            </div>
          </div>
          <div className="mt-6">
            <Button
              onClick={handleRunEvaluation}
              disabled={isRunning || !selectedDataset || !selectedVersionA}
              className="w-full"
              size="lg"
            >
              {isRunning ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Running Evaluation...
                </>
              ) : (
                <>
                  <Play className="mr-2 h-4 w-4" />
                  Run Evaluation
                </>
              )}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
