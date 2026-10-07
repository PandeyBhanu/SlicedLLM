import type { DiffSegment, TokenDiff } from '@/types/api';
import { Pill } from '@/components/ui/bits';

// Make whitespace visible so whitespace-only changes are not invisible.
function visible(text: string): string {
  return text.replace(/\t/g, '→\t').replace(/ {2,}/g, (m) => '·'.repeat(m.length)).replace(/\r?\n/g, (m) => (m.length === 2 ? '␍↵\n' : '↵\n'));
}

const STYLE: Record<DiffSegment['op'], string> = {
  equal: '',
  insert: 'bg-green-200/70 text-green-900',
  delete: 'bg-red-200/70 text-red-900 line-through decoration-red-500/60',
};

/** Renders a diff as React text nodes (React escapes them) - never via dangerouslySetInnerHTML. */
export function DiffView({ diff }: { diff: TokenDiff }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Pill tone="blue">{diff.granularity} diff</Pill>
        <Pill>
          tokenizer: {diff.tokenizer}
          {diff.approximate_tokenizer ? ' (approximate)' : ''}
        </Pill>
        <Pill tone="green">+{diff.stats.added} tokens</Pill>
        <Pill tone="red">-{diff.stats.removed} tokens</Pill>
        <Pill>{(diff.stats.similarity * 100).toFixed(0)}% similar</Pill>
        <Pill>{diff.original_tokens} → {diff.modified_tokens} tokens</Pill>
        {diff.algorithm === 'line-anchored' && <Pill>line-anchored</Pill>}
        {diff.coarse && <Pill tone="red">some hunks too large: shown as whole replacements</Pill>}
      </div>
      <pre className="max-h-[28rem] overflow-auto whitespace-pre-wrap break-words rounded-md border bg-muted/30 p-3 font-mono text-sm">
        {diff.segments.length === 0 && <span className="text-muted-foreground">(both versions are empty)</span>}
        {diff.segments.map((s, i) => (
          <span key={i} className={STYLE[s.op]} title={`${s.op} · ${s.token_count} token(s)`}>
            {visible(s.text)}
          </span>
        ))}
      </pre>
    </div>
  );
}
