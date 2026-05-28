'use client';

import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { usePrompts, useCreatePrompt, useDeletePrompt, useVersions, useActivateVersion } from '@/hooks/use-api';
import { Plus, Trash2, Play, Tag, FileText, Clock } from 'lucide-react';
import { format } from 'date-fns';

export default function PromptsPage() {
  const { data: prompts, isLoading } = usePrompts();
  const createPromptMutation = useCreatePrompt();
  const deletePromptMutation = useDeletePrompt();
  const activateVersionMutation = useActivateVersion();
  const [selectedPrompt, setSelectedPrompt] = useState<string | null>(null);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [newPromptName, setNewPromptName] = useState('');
  const [newPromptDescription, setNewPromptDescription] = useState('');

  const { data: versions } = useVersions(selectedPrompt || '');

  const handleCreatePrompt = () => {
    if (newPromptName) {
      createPromptMutation.mutate({
        name: newPromptName,
        description: newPromptDescription,
      });
      setShowCreateDialog(false);
      setNewPromptName('');
      setNewPromptDescription('');
    }
  };

  const handleDeletePrompt = (id: string) => {
    if (confirm('Are you sure you want to delete this prompt?')) {
      deletePromptMutation.mutate(id);
    }
  };

  const handleActivateVersion = (versionId: string) => {
    activateVersionMutation.mutate(versionId);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Prompt Registry</h1>
          <p className="text-muted-foreground">
            Manage your prompt templates and versions
          </p>
        </div>
        <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="mr-2 h-4 w-4" />
              New Prompt
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Create New Prompt</DialogTitle>
              <DialogDescription>
                Create a new prompt template for versioning and evaluation
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4 py-4">
              <div>
                <label className="text-sm font-medium">Name</label>
                <input
                  type="text"
                  value={newPromptName}
                  onChange={(e) => setNewPromptName(e.target.value)}
                  className="w-full mt-1 px-3 py-2 border rounded-md"
                  placeholder="prompt-name"
                />
              </div>
              <div>
                <label className="text-sm font-medium">Description</label>
                <textarea
                  value={newPromptDescription}
                  onChange={(e) => setNewPromptDescription(e.target.value)}
                  className="w-full mt-1 px-3 py-2 border rounded-md"
                  placeholder="Description of the prompt..."
                  rows={3}
                />
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setShowCreateDialog(false)}>
                Cancel
              </Button>
              <Button onClick={handleCreatePrompt}>Create</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Prompts</CardTitle>
            <CardDescription>
              All registered prompts in your registry
            </CardDescription>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="text-sm text-muted-foreground">Loading...</div>
            ) : !prompts || prompts.length === 0 ? (
              <div className="text-sm text-muted-foreground">No prompts registered yet</div>
            ) : (
              <div className="space-y-2">
                {prompts.map((prompt) => (
                  <div
                    key={prompt.id}
                    className={`p-3 rounded-lg border cursor-pointer transition-colors ${
                      selectedPrompt === prompt.id
                        ? 'bg-primary text-primary-foreground'
                        : 'hover:bg-accent'
                    }`}
                    onClick={() => setSelectedPrompt(prompt.id)}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <FileText className="h-4 w-4" />
                        <span className="font-medium">{prompt.name}</span>
                      </div>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeletePrompt(prompt.id);
                        }}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                    {prompt.description && (
                      <p className="text-xs mt-1 opacity-80">{prompt.description}</p>
                    )}
                    {prompt.tags && prompt.tags.length > 0 && (
                      <div className="flex gap-1 mt-2">
                        {prompt.tags.map((tag) => (
                          <span
                            key={tag}
                            className="text-xs bg-secondary px-2 py-0.5 rounded"
                          >
                            {tag}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {selectedPrompt && (
          <Card>
            <CardHeader>
              <CardTitle>Versions</CardTitle>
              <CardDescription>
                Version history for selected prompt
              </CardDescription>
            </CardHeader>
            <CardContent>
              {!versions || versions.length === 0 ? (
                <div className="text-sm text-muted-foreground">No versions yet</div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Version</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Created</TableHead>
                      <TableHead>Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {versions.map((version) => (
                      <TableRow key={version.id}>
                        <TableCell className="font-medium">
                          {version.semantic_version}
                        </TableCell>
                        <TableCell>
                          {version.is_active ? (
                            <span className="text-green-600 text-xs font-medium">
                              Active
                            </span>
                          ) : (
                            <span className="text-muted-foreground text-xs">
                              Inactive
                            </span>
                          )}
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1 text-xs text-muted-foreground">
                            <Clock className="h-3 w-3" />
                            {format(new Date(version.created_at), 'MMM d, yyyy')}
                          </div>
                        </TableCell>
                        <TableCell>
                          {!version.is_active && (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleActivateVersion(version.id)}
                            >
                              <Play className="h-3 w-3 mr-1" />
                              Activate
                            </Button>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
