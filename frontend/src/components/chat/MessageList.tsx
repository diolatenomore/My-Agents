import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowDown, MessagesSquare } from 'lucide-react';
import { useChatStore } from '../../stores/chatStore';
import { useAppStore } from '../../stores/appStore';
import UserBubble from './UserBubble';
import TurnView from './TurnView';

function ChatEmpty({ noModel }: { noModel: boolean }) {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-indigo-50 text-indigo-500">
        <MessagesSquare size={26} />
      </div>
      <div className="mt-4 text-base font-semibold text-zinc-700">开始新的对话</div>
      {noModel && (
        <div className="mt-4 rounded-lg bg-amber-50 px-3.5 py-2 text-xs text-amber-700">
          还没有可用的模型配置，请先前往
          <Link to="/models" className="font-medium underline underline-offset-2">
            模型管理
          </Link>
          添加
        </div>
      )}
    </div>
  );
}

export default function MessageList() {
  const entries = useChatStore(s => s.entries);
  const historyLoading = useChatStore(s => s.historyLoading);
  const models = useAppStore(s => s.models);
  const selectedModelId = useAppStore(s => s.selectedModelId);

  const containerRef = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);

  const noModel = models.length === 0 || !selectedModelId;

  useEffect(() => {
    const el = containerRef.current;
    if (!el || !atBottom) return;
    el.scrollTop = el.scrollHeight;
  });

  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 80);
  };

  const scrollToBottom = () => {
    const el = containerRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    setAtBottom(true);
  };

  return (
    <div className="relative min-h-0 flex-1">
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="nice-scroll h-full overflow-y-auto bg-zinc-50"
      >
        <div className="mx-auto w-full max-w-3xl px-6 py-6">
          {historyLoading ? (
            <div className="py-24 text-center text-sm text-zinc-400">加载会话消息中…</div>
          ) : entries.length === 0 ? (
            <ChatEmpty noModel={noModel} />
          ) : (
            entries.map(e =>
              e.kind === 'user' ? (
                <UserBubble key={e.id} content={e.content} segments={e.segments} />
              ) : (
                <TurnView key={e.id} turn={e} />
              ),
            )
          )}
        </div>
      </div>

      {!atBottom && (
        <button
          className="absolute bottom-4 left-1/2 flex h-8 w-8 -translate-x-1/2 items-center justify-center rounded-full border border-zinc-200 bg-white text-zinc-500 shadow-md transition-colors hover:text-zinc-800"
          title="滚动到底部"
          onClick={scrollToBottom}
        >
          <ArrowDown size={15} />
        </button>
      )}
    </div>
  );
}
