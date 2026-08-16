import { AlertTriangle, Bot, OctagonX } from 'lucide-react';
import type { TurnBlockView, TurnEntry } from '../../types';
import { useChatStore } from '../../stores/chatStore';
import ThinkingView from './ThinkingView';
import Markdown from './Markdown';
import ToolCard from './ToolCard';
import IterationCard from './IterationCard';

function ErrorNote({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-[13px] text-red-600">
      <AlertTriangle size={15} className="mt-0.5 shrink-0" />
      <span className="whitespace-pre-wrap break-words">{message}</span>
    </div>
  );
}

export default function TurnView({ turn }: { turn: TurnEntry }) {
  const streaming = turn.status === 'streaming';
  // 状态提示只跟随当前正在流式的轮次
  const streamLabel = useChatStore(s => (streaming ? s.streamLabel : ''));

  return (
    <div className="flex gap-3 py-2">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-zinc-200 bg-white text-zinc-500">
        <Bot size={15} />
      </div>
      <div className="min-w-0 flex-1 space-y-2.5 pb-1">
        {turn.blocks.map(b => (
          <TurnBlock key={b.id} turnId={turn.id} block={b} />
        ))}

        {streaming && streamLabel && (
          <div className="flex items-center gap-1.5 text-xs text-zinc-400">
            <span className="pulse-dot h-1.5 w-1.5 rounded-full bg-indigo-400" />
            {streamLabel}
          </div>
        )}

        {turn.status === 'cancelled' && (
          <div className="flex items-center gap-1.5 text-xs text-amber-600">
            <OctagonX size={13} />
            已中断
          </div>
        )}
        {turn.status === 'done' && turn.note && (
          <div className="text-xs text-amber-600">{turn.note}</div>
        )}
      </div>
    </div>
  );
}

function TurnBlock({ turnId, block }: { turnId: string; block: TurnBlockView }) {
  switch (block.kind) {
    case 'thinking':
      return <ThinkingView block={block} />;
    case 'text':
      return <Markdown content={block.content} />;
    case 'tool':
      return <ToolCard turnId={turnId} block={block} />;
    case 'iteration':
      return <IterationCard turnId={turnId} block={block} />;
    case 'error-note':
      return <ErrorNote message={block.message} />;
  }
}
