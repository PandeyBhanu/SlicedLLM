'use client';

import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { usePrompts, useVersions, useVersionDiff } from '@/hooks/use-api';
import { GitCompare, ArrowLeft, Plus, Minus } from 'lucide-react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';

export default function DiffPage() {
  const { data: prompts } = usePrompts();
  const [selectedPrompt, setSelectedPrompt] = useState<string | null>(null);
  const [versionA, setVersionA] = useState<string | null>(null);
  const [versionB, setVersionB] = useState<string | null>(null);
  
  const { data: versions } = useVersions(selectedPrompt || '');
  const { data: diffData, isLoading: diffLoading } = useVersionDiff(
    versionA || '',
    versionB || ''
  );

  const handlePromptSelect = (promptId: string) => {
    setSelectedPrompt(promptId);
    setVersionA(null);
    setVersionB(null);
  };

  const renderDiffSegment = (segment: any, index: number) => {
    const bgColor = segment.change_type === 'added' 
      ? 'bg-green-500/20' 
      : segment.change_type === 'removed' 
      ? 'bg-red-500/20' 
      : 'bg-transparent';
    
    const icon = segment.change_type === 'added' 
      ? <Plus className="h-3 w-3 text-green-500" />
      : segment.change_type === 'removed' 
      ? <Minus className="h-3 w-3 text-red-500" />
      : null;

    return (
      <div key={index} className={`flex items-start gap-2 ${bgColor} px-2 py-1`}>
        {icon && <span className="mt-1">{icon}</span>}
        <span className="text-sm font-mono">{segment.content}</span>
      </div>
    );
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Prompt Diff View</h1>
        <p className="text-muted-foreground">
          Compare prompt versions side-by-side
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Select Prompt</CardTitle>
            <CardDescription>Choose a prompt to compare versions</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {prompts?.map((prompt) => (
                <button
                  key={prompt.id}
                  onClick={() => handlePromptSelect(prompt.id)}
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
          <>
            <Card>
              <CardHeader>
                <CardTitle>Version A</CardTitle>
                <CardDescription>Select first version</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {versions?.map((version) => (
                    <button
                      key={version.id}
                      onClick={() => setVersionA(version.id)}
                      className={`w-full text-left p-3 rounded-lg border transition-colors ${
                        versionA === version.id
                          ? 'bg-primary text-primary-foreground'
                          : 'hover:bg-accent'
                      }`}
                    >
                      <div className="font-medium">{version.semantic_version}</div>
                      <div className="text-xs opacity-80 mt-1">
                        {version.is_active ? 'Active' : 'Inactive'}
                      </div>
                    </button>
                  ))}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Version B</CardTitle>
                <CardDescription>Select second version</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {versions?.map((version) => (
                    <button
                      key={version.id}
                      onClick={() => setVersionB(version.id)}
                      className={`w-full text-left p-3 rounded-lg border transition-colors ${
                        versionB === version.id
                          ? 'bg-primary text-primary-foreground'
                          : 'hover:bg-accent'
                      }`}
                    >
                      <div className="font-medium">{version.semantic_version}</div>
                      <div className="text-xs opacity-80 mt-1">
                        {version.is_active ? 'Active' : 'Inactive'}
                      </div>
                    </button>
                  ))}
                </div>
              </CardContent>
            </Card>
          </>
        )}
      </div>

      {diffData && !diffLoading && (
        <div className="grid gap-6 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <GitCompare className="h-5 w-5" />
                Version A
              </CardTitle>
              <CardDescription>
                {diffData.version_a?.semantic_version}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <SyntaxHighlighter
                language="text"
                style={vscDarkPlus}
                customStyle={{
                  borderRadius: '0.5rem',
                  fontSize: '0.875rem',
                }}
              >
                {diffData.version_a?.template || ''}
              </SyntaxHighlighter>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <GitCompare className="h-5 w-5" />
                Version B
              </CardTitle>
              <CardDescription>
                {diffData.version_b?.semantic_version}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <SyntaxHighlighter
                language="text"
                style={vscDarkPlus}
                customStyle={{
                  borderRadius: '0.5rem',
                  fontSize: '0.875rem',
                }}
              >
                {diffData.version_b?.template || ''}
              </SyntaxHighlighter>
            </CardContent>
          </Card>
        </div>
      )}

      {diffData && !diffLoading && diffData.diff && (
        <Card>
          <CardHeader>
            <CardTitle>Diff Analysis</CardTitle>
            <CardDescription>
              Detailed comparison between versions
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="grid grid-cols-3 gap-4 text-sm">
                <div className="p-3 bg-green-500/10 rounded-lg">
                  <div className="font-medium text-green-600">Additions</div>
                  <div className="text-2xl font-bold">{diffData.diff.additions}</div>
                </div>
                <div className="p-3 bg-red-500/10 rounded-lg">
                  <div className="font-medium text-red-600">Deletions</div>
                  <div className="text-2xl font-bold">{diffData.diff.deletions}</div>
                </div>
                <div className="p-3 bg-blue-500/10 rounded-lg">
                  <div className="font-medium text-blue-600">Similarity</div>
                  <div className="text-2xl font-bold">
                    {(diffData.diff.similarity_ratio * 100).toFixed(0)}%
                  </div>
                </div>
              </div>

              {diffData.diff.segments && diffData.diff.segments.length > 0 && (
                <div className="border rounded-lg p-4 bg-background">
                  <div className="font-medium mb-3">Diff Segments</div>
                  <div className="space-y-1 font-mono">
                    {diffData.diff.segments.map(renderDiffSegment)}
                  </div>
                </div>
              )}

              {diffData.variables && (
                <div className="border rounded-lg p-4 bg-background">
                  <div className="font-medium mb-3">Variable Changes</div>
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <div>
                      <div className="text-muted-foreground mb-2">Added Variables</div>
                      <div className="space-y-1">
                        {diffData.variables.added?.map((v: string, i: number) => (
                          <div key={i} className="text-green-600">+ {v}</div>
                        ))}
                      </div>
                    </div>
                    <div>
                      <div className="text-muted-foreground mb-2">Removed Variables</div>
                      <div className="space-y-1">
                        {diffData.variables.removed?.map((v: string, i: number) => (
                          <div key={i} className="text-red-600">- {v}</div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
