import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Send, Square } from 'lucide-react';
import { useAppStore } from '../../stores/appStore';
import { useChatStore } from '../../stores/chatStore';

export default function ChatInput() {
  const [text, setText] = useState('');
  const streaming = useChatStore(s => s.streaming);
  const send = useChatStore(s => s.send);
  const stop = useChatStore(s => s.stop);
  const models = useAppStore(s => s.models);
  const modelsLoading = useAppStore(s => s.modelsLoading);
  const selectedModelId = useAppStore(s => s.selectedModelId);

  const noModel = !modelsLoading && (models.length === 0 || !selectedModelId);
  const taRef = useRef<HTMLTextAreaElement>(null);

  // 自适应高度（1~8 行）
  useEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [text]);

  const canSend = text.trim().length > 0 && !streaming && !noModel;

  const handleSend = () => {
    if (!canSend) return;
    const q = text.trim();
    setText('');
    void send(q);
  };

  return (
    <div className="shrink-0 border-t border-zinc-200 bg-white px-6 pt-4 pb-4">
      <div className="mx-auto w-full max-w-3xl">
        {noModel && (
          <div className="mb-2 flex items-center gap-1.5 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">
            未选择模型，发送前请先前往
            <Link to="/models" className="font-medium underline underline-offset-2">
              模型管理
            </Link>
            添加并选择模型
          </div>
        )}
        <div className="rounded-2xl border border-zinc-300 bg-white shadow-sm transition focus-within:border-indigo-400 focus-within:ring-2 focus-within:ring-indigo-100">
          <textarea
            ref={taRef}
            rows={1}
            className="nice-scroll block max-h-[200px] w-full resize-none bg-transparent px-4 pt-3.5 pb-1 text-sm leading-relaxed outline-none placeholder:text-zinc-400"
            placeholder="输入消息…"
            value={text}
            onChange={e => setText(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                handleSend();
              }
            }}
          />
          <div className="flex items-center justify-between px-3 pt-1 pb-2.5">
            <span className="text-[11px] text-zinc-400">Enter 发送 · Shift+Enter 换行</span>
            {streaming ? (
              <button className="btn bg-zinc-800 text-white hover:bg-zinc-700" onClick={() => void stop()}>
                <Square size={12} fill="currentColor" />
                停止
              </button>
            ) : (
              <button className="btn btn-primary" disabled={!canSend} onClick={handleSend}>
                <Send size={13} />
                发送
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
