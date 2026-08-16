import { useEffect, useState } from 'react';
import { Brain, ChevronDown } from 'lucide-react';
import type { ThinkingBlockView } from '../../types';
import { cn } from '../../utils/misc';

/** 思考过程折叠块：流式时自动展开，首个可见 token 到达（streaming=false）后自动折叠 */
export default function ThinkingView({ block }: { block: ThinkingBlockView }) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setOpen(block.streaming);
  }, [block.streaming]);

  return (
    <div className="rounded-lg border border-zinc-200 bg-zinc-50/70">
      <button
        className="flex w-full cursor-pointer items-center gap-1.5 px-3 py-2 text-xs text-zinc-500"
        onClick={() => setOpen(!open)}
      >
        <Brain size={13} className={cn(block.streaming && 'pulse-dot text-indigo-400')} />
        <span>{block.streaming ? '思考中…' : '思考过程'}</span>
        <span className="text-[10px] text-zinc-400">{block.content.length} 字</span>
        <ChevronDown size={13} className={cn('ml-auto transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="nice-scroll max-h-72 overflow-y-auto border-t border-zinc-200 px-3 py-2.5 font-mono text-xs leading-relaxed whitespace-pre-wrap text-zinc-500">
          {block.content}
        </div>
      )}
    </div>
  );
}
