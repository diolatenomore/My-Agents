import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Send, Square } from 'lucide-react';
import { useAppStore } from '../../stores/appStore';
import { useChatStore } from '../../stores/chatStore';
import { listSkills } from '../../api/skills';
import type { SkillInfo } from '../../types';
import TodoBar from './TodoBar';
import SkillComposer, { type ComposerValue, type SkillComposerHandle } from './SkillComposer';

const EMPTY_VALUE: ComposerValue = { text: '', skills: [], segments: [] };

export default function ChatInput() {
  const [value, setValue] = useState<ComposerValue>(EMPTY_VALUE);
  const [skillList, setSkillList] = useState<SkillInfo[]>([]);
  const streaming = useChatStore(s => s.streaming);
  const send = useChatStore(s => s.send);
  const stop = useChatStore(s => s.stop);
  const models = useAppStore(s => s.models);
  const modelsLoading = useAppStore(s => s.modelsLoading);
  const selectedModelId = useAppStore(s => s.selectedModelId);

  const noModel = !modelsLoading && (models.length === 0 || !selectedModelId);
  const composerRef = useRef<SkillComposerHandle>(null);

  const refreshSkills = useCallback(async () => {
    try {
      const res = await listSkills();
      setSkillList(res.skills.filter(s => !s.disabled));
    } catch {
      // 技能列表加载失败不阻塞聊天，仅 "/" 补全不可用
    }
  }, []);

  useEffect(() => {
    void refreshSkills();
  }, [refreshSkills]);

  const canSend = value.text.trim().length > 0 && !streaming && !noModel;

  const handleSend = () => {
    if (!canSend) return;
    const q = value.text;
    const skills = value.skills;
    const segments = value.segments;
    composerRef.current?.clear();
    void send(q, skills, segments);
  };

  return (
    <div className="shrink-0 border-t border-zinc-200 bg-white px-6 pt-4 pb-4">
      <div className="mx-auto w-full max-w-3xl">
        <TodoBar />
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
          <SkillComposer
            ref={composerRef}
            placeholder="输入消息…"
            skills={skillList}
            onValueChange={setValue}
            onSend={handleSend}
            onMenuOpen={() => void refreshSkills()}
          />
          <div className="flex items-center justify-between px-3 pt-1 pb-2.5">
            <span className="text-[11px] text-zinc-400">Enter 发送 · Shift+Enter 换行 · / 插入技能</span>
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
