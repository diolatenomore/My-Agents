import { useAppStore } from '../../stores/appStore';
import { useChatStore } from '../../stores/chatStore';
import { cn } from '../../utils/misc';

/** 上下文 token 用量：占所选模型 max_context_tokens 的百分比（颜色分级） */
export default function ContextUsageBar() {
  const tokens = useChatStore(s => s.contextTokens);
  const models = useAppStore(s => s.models);
  const selectedModelId = useAppStore(s => s.selectedModelId);
  const model = models.find(m => m.id === selectedModelId);
  const limit = model?.max_context_tokens ?? 0;

  if (tokens <= 0) return null;

  const pct = limit > 0 ? Math.min(100, (tokens / limit) * 100) : null;
  const barColor =
    pct == null ? 'bg-zinc-400' : pct < 60 ? 'bg-emerald-500' : pct < 85 ? 'bg-amber-500' : 'bg-red-500';

  return (
    <div
      className="flex items-center gap-2"
      title={limit > 0 ? `上下文 ${tokens.toLocaleString()} / ${limit.toLocaleString()} tokens` : undefined}
    >
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-zinc-200">
        <div
          className={cn('h-full rounded-full transition-all', barColor)}
          style={{ width: pct != null ? `${pct}%` : '100%' }}
        />
      </div>
      <span className="text-xs whitespace-nowrap text-zinc-500">
        {tokens.toLocaleString()}
        {pct != null ? ` · ${pct.toFixed(0)}%` : ' tokens'}
      </span>
    </div>
  );
}
