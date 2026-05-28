'use client';

import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { usePrompts, useChangelog, usePromptAuditHistory } from '@/hooks/use-api';
import { History, GitCommit, Clock, User, ArrowRight } from 'lucide-react';
import { format } from 'date-fns';

export default function ChangelogPage() {
  const { data: prompts } = usePrompts();
  const [selectedPrompt, setSelectedPrompt] = useState<string | null>(null);
  const { data: changelog } = useChangelog(selectedPrompt || '', true);
  const { data: auditHistory } = usePromptAuditHistory(selectedPrompt || '');

  const selectedPromptData = prompts?.find(p => p.id === selectedPrompt);

  const getChangeIcon = (changeType: string) => {
    switch (changeType) {
      case 'created':
        return <GitCommit className="h-4 w-4 text-green-500" />;
      case 'activated':
        return <GitCommit className="h-4 w-4 text-blue-500" />;
      case 'rollback':
        return <GitCommit className="h-4 w-4 text-orange-500" />;
      default:
        return <GitCommit className="h-4 w-4 text-gray-500" />;
    }
  };

  const getActionIcon = (action: string) => {
    switch (action) {
      case 'CREATE':
        return <GitCommit className="h-4 w-4 text-green-500" />;
      case 'UPDATE':
        return <GitCommit className="h-4 w-4 text-blue-500" />;
      case 'ACTIVATE':
        return <GitCommit className="h-4 w-4 text-purple-500" />;
      case 'ROLLBACK':
        return <GitCommit className="h-4 w-4 text-orange-500" />;
      default:
        return <GitCommit className="h-4 w-4 text-gray-500" />;
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Changelog & Audit History</h1>
        <p className="text-muted-foreground">
          Track version changes and audit history for your prompts
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <History className="h-5 w-5" />
              Select Prompt
            </CardTitle>
            <CardDescription>Choose a prompt to view history</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {prompts?.map((prompt) => (
                <button
                  key={prompt.id}
                  onClick={() => setSelectedPrompt(prompt.id)}
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
            <Card className="md:col-span-2">
              <CardHeader>
                <CardTitle>Version Changelog</CardTitle>
                <CardDescription>
                  {selectedPromptData?.name} - Version history
                </CardDescription>
              </CardHeader>
              <CardContent>
                {!changelog || changelog.length === 0 ? (
                  <div className="text-sm text-muted-foreground">No changelog entries</div>
                ) : (
                  <div className="space-y-4">
                    {changelog.map((entry, index) => (
                      <div key={index} className="flex gap-4">
                        <div className="flex flex-col items-center">
                          <div className="w-8 h-8 rounded-full bg-background border flex items-center justify-center">
                            {getChangeIcon(entry.change_type)}
                          </div>
                          {index < changelog.length - 1 && (
                            <div className="w-0.5 h-full bg-border mt-2" />
                          )}
                        </div>
                        <div className="flex-1 pb-6">
                          <div className="flex items-center gap-2">
                            <span className="font-medium">{entry.semantic_version}</span>
                            {entry.is_active && (
                              <span className="text-xs bg-green-500 px-2 py-0.5 rounded text-white">
                                Active
                              </span>
                            )}
                          </div>
                          <div className="text-sm text-muted-foreground mt-1">
                            {entry.description}
                          </div>
                          {entry.timestamp && (
                            <div className="flex items-center gap-1 text-xs text-muted-foreground mt-2">
                              <Clock className="h-3 w-3" />
                              {format(new Date(entry.timestamp), 'MMM d, yyyy HH:mm')}
                            </div>
                          )}
                          {entry.diff && (
                            <div className="mt-3 p-3 bg-muted rounded-lg text-sm">
                              <div className="font-medium mb-2">Diff Summary</div>
                              <div className="grid grid-cols-3 gap-2 text-xs">
                                <div>
                                  <span className="text-green-600">+{entry.diff.diff.additions}</span> additions
                                </div>
                                <div>
                                  <span className="text-red-600">-{entry.diff.diff.deletions}</span> deletions
                                </div>
                                <div>
                                  {(entry.diff.diff.similarity_ratio * 100).toFixed(0)}% similar
                                </div>
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </>
        )}
      </div>

      {selectedPrompt && auditHistory && auditHistory.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Audit History</CardTitle>
            <CardDescription>
              Complete audit trail of all operations
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {auditHistory.map((entry, index) => (
                <div key={index} className="flex gap-4 items-start">
                  <div className="w-8 h-8 rounded-full bg-background border flex items-center justify-center">
                    {getActionIcon(entry.action)}
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{entry.action}</span>
                      <span className="text-xs text-muted-foreground">
                        {entry.entity_type}
                      </span>
                    </div>
                    <div className="flex items-center gap-1 text-xs text-muted-foreground mt-1">
                      <Clock className="h-3 w-3" />
                      {entry.timestamp ? format(new Date(entry.timestamp), 'MMM d, yyyy HH:mm') : 'N/A'}
                    </div>
                    {entry.before_state && (
                      <div className="mt-2 p-2 bg-red-500/10 rounded text-xs">
                        <div className="font-medium text-red-600 mb-1">Before:</div>
                        <pre className="text-muted-foreground overflow-x-auto">
                          {JSON.stringify(entry.before_state, null, 2)}
                        </pre>
                      </div>
                    )}
                    {entry.after_state && (
                      <div className="mt-2 p-2 bg-green-500/10 rounded text-xs">
                        <div className="font-medium text-green-600 mb-1">After:</div>
                        <pre className="text-muted-foreground overflow-x-auto">
                          {JSON.stringify(entry.after_state, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
