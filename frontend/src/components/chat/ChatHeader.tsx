import { useNavigate } from 'react-router-dom';
import { PanelRight, Settings2 } from 'lucide-react';
import { useAppStore } from '../../stores/appStore';
import { useChatStore } from '../../stores/chatStore';
import { useReviewStore } from '../../stores/reviewStore';
import { cn } from '../../utils/misc';
import ModelSelect from './ModelSelect';
import ContextUsageBar from './ContextUsageBar';

export default function ChatHeader() {
  const navigate = useNavigate();
  const sessions = useAppStore(s => s.sessions);
  const currentSessionId = useAppStore(s => s.currentSessionId);
  const streaming = useChatStore(s => s.streaming);
  const streamLabel = useChatStore(s => s.streamLabel);
  const drawerOpen = useReviewStore(s => s.open);
  const hasReview = useReviewStore(s => s.tree !== null);
  const setOpen = useReviewStore(s => s.setOpen);

  const session = sessions.find(s => s.session_id === currentSessionId);
  const title = currentSessionId ? session?.title || '未命名会话' : '新会话';

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-zinc-200 bg-white px-5">
      <div className="flex min-w-0 items-center gap-3">
        <h2 className="truncate text-sm font-semibold text-zinc-800">{title}</h2>
        {streaming && (
          <span className="flex shrink-0 items-center gap-1.5 rounded-full bg-indigo-50 px-2.5 py-0.5 text-[11px] font-medium text-indigo-600">
            <span className="pulse-dot h-1.5 w-1.5 rounded-full bg-indigo-500" />
            {streamLabel || '处理中…'}
          </span>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-3">
        <ContextUsageBar />
        <ModelSelect />
        <button
          className="icon-btn"
          title="模型管理"
          onClick={() => navigate('/models')}
        >
          <Settings2 size={16} />
        </button>
        <button
          className={cn('icon-btn relative', drawerOpen && 'bg-zinc-100 text-zinc-700')}
          title="审批面板"
          onClick={() => setOpen(!drawerOpen)}
        >
          <PanelRight size={16} />
          {hasReview && !drawerOpen && (
            <span className="absolute top-1 right-1 h-1.5 w-1.5 rounded-full bg-amber-500" />
          )}
        </button>
      </div>
    </header>
  );
}
