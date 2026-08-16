import { useMemo, useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import {
  Bot,
  Brain,
  Cpu,
  MessageSquarePlus,
  MessagesSquare,
  Pencil,
  Search,
  Sparkles,
  Trash2,
} from 'lucide-react';
import { useAppStore } from '../../stores/appStore';
import { newSession, removeSession, renameSessionAction, switchSession } from '../../stores/actions';
import { cn, formatRelativeTime } from '../../utils/misc';
import Modal from '../common/Modal';
import type { SessionDTO } from '../../types';

const NAV_ITEMS = [
  { to: '/', icon: MessagesSquare, label: '聊天', end: true },
  { to: '/memory', icon: Brain, label: '记忆' },
  { to: '/skills', icon: Sparkles, label: '技能' },
  { to: '/models', icon: Cpu, label: '模型' },
];

export default function Sidebar() {
  const navigate = useNavigate();
  const sessions = useAppStore(s => s.sessions);
  const currentSessionId = useAppStore(s => s.currentSessionId);
  const [search, setSearch] = useState('');
  const [renaming, setRenaming] = useState<SessionDTO | null>(null);
  const [renameValue, setRenameValue] = useState('');

  const filtered = useMemo(() => {
    const kw = search.trim().toLowerCase();
    if (!kw) return sessions;
    return sessions.filter(
      s =>
        (s.title || '').toLowerCase().includes(kw) || s.session_id.toLowerCase().includes(kw),
    );
  }, [sessions, search]);

  const handleSwitch = (sid: string) => {
    void switchSession(sid);
    navigate('/');
  };

  const handleNew = () => {
    newSession();
    navigate('/');
  };

  const confirmRename = async () => {
    if (!renaming) return;
    const title = renameValue.trim();
    setRenaming(null);
    if (title && title !== renaming.title) {
      await renameSessionAction(renaming.session_id, title);
    }
  };

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-zinc-200 bg-white">
      {/* 品牌 */}
      <div className="flex items-center gap-2.5 px-4 pt-4 pb-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-white">
          <Bot size={18} />
        </div>
        <div>
          <div className="text-sm font-semibold text-zinc-800">AI Agents</div>
          <div className="text-[11px] text-zinc-400">ReAct 智能体工作台</div>
        </div>
      </div>

      {/* 新建会话 */}
      <div className="px-3 pb-2">
        <button className="btn btn-primary w-full" onClick={handleNew}>
          <MessageSquarePlus size={16} />
          新建会话
        </button>
      </div>

      {/* 搜索 */}
      <div className="px-3 pb-2">
        <div className="relative">
          <Search size={14} className="absolute top-1/2 left-2.5 -translate-y-1/2 text-zinc-400" />
          <input
            className="input py-1.5 pr-3 pl-8 text-[13px]"
            placeholder="搜索会话"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
      </div>

      {/* 会话列表 */}
      <nav className="nice-scroll min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {filtered.length === 0 ? (
          <div className="px-3 py-8 text-center text-xs text-zinc-400">
            {sessions.length === 0 ? '暂无会话，发送消息开始' : '没有匹配的会话'}
          </div>
        ) : (
          filtered.map(s => {
            const active = s.session_id === currentSessionId;
            const title = s.title || `${s.session_id.slice(0, 8)}…`;
            return (
              <div
                key={s.session_id}
                className={cn(
                  'group mb-0.5 cursor-pointer rounded-lg px-3 py-2 transition-colors',
                  active ? 'bg-indigo-50' : 'hover:bg-zinc-100',
                )}
                onClick={() => handleSwitch(s.session_id)}
              >
                <div className="flex items-center justify-between gap-1">
                  <span
                    className={cn(
                      'truncate text-[13px] font-medium',
                      active ? 'text-indigo-700' : 'text-zinc-700',
                    )}
                  >
                    {title}
                  </span>
                  <span className="hidden shrink-0 items-center group-hover:flex">
                    <button
                      className="icon-btn h-6 w-6"
                      title="重命名"
                      onClick={e => {
                        e.stopPropagation();
                        setRenameValue(s.title);
                        setRenaming(s);
                      }}
                    >
                      <Pencil size={12} />
                    </button>
                    <button
                      className="icon-btn h-6 w-6 hover:text-red-500"
                      title="删除"
                      onClick={e => {
                        e.stopPropagation();
                        void removeSession(s.session_id);
                      }}
                    >
                      <Trash2 size={12} />
                    </button>
                  </span>
                </div>
                <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-zinc-400">
                  <span>{s.message_count} 条消息</span>
                  <span>·</span>
                  <span>{formatRelativeTime(s.updated_at)}</span>
                </div>
              </div>
            );
          })
        )}
      </nav>

      {/* 底部导航 */}
      <nav className="border-t border-zinc-100 p-2">
        {NAV_ITEMS.map(({ to, icon: Icon, label, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] font-medium transition-colors',
                isActive ? 'bg-indigo-50 text-indigo-700' : 'text-zinc-500 hover:bg-zinc-100 hover:text-zinc-800',
              )
            }
          >
            <Icon size={16} />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* 重命名弹窗 */}
      <Modal
        open={renaming !== null}
        title="重命名会话"
        onClose={() => setRenaming(null)}
        width="max-w-sm"
        footer={
          <>
            <button className="btn btn-outline" onClick={() => setRenaming(null)}>
              取消
            </button>
            <button className="btn btn-primary" onClick={() => void confirmRename()}>
              保存
            </button>
          </>
        }
      >
        <input
          className="input"
          maxLength={50}
          placeholder="输入新标题（≤50 字）"
          value={renameValue}
          autoFocus
          onChange={e => setRenameValue(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.nativeEvent.isComposing) void confirmRename();
          }}
        />
      </Modal>
    </aside>
  );
}
