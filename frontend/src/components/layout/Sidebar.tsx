import { useMemo, useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import {
  Bot,
  Brain,
  ChevronDown,
  Cpu,
  FolderOpen,
  MessageSquarePlus,
  Pencil,
  Plus,
  Sparkles,
  Trash2,
} from 'lucide-react';
import { useAppStore } from '../../stores/appStore';
import { newSessionInProject, removeSession, renameSessionAction, switchSession } from '../../stores/actions';
import { cn, formatRelativeTime } from '../../utils/misc';
import Modal from '../common/Modal';
import ProjectManagerDialog from '../project/ProjectManagerDialog';
import type { SessionDTO } from '../../types';

const NAV_ITEMS = [
  { to: '/memory', icon: Brain, label: '记忆' },
  { to: '/skills', icon: Sparkles, label: '技能' },
  { to: '/models', icon: Cpu, label: '模型' },
];

const CHATS_OPEN_KEY = 'sidebar_chats_open';
const PROJECTS_OPEN_KEY = 'sidebar_projects_open';
const PROJECT_COLLAPSED_KEY = 'sidebar_collapsed_projects';

function readOpenFlag(key: string): boolean {
  return localStorage.getItem(key) !== '0';
}

function readCollapsedProjects(): Record<string, boolean> {
  try {
    return JSON.parse(localStorage.getItem(PROJECT_COLLAPSED_KEY) ?? '{}') as Record<string, boolean>;
  } catch {
    return {};
  }
}

/** 会话条目：标题 + 悬停重命名/删除 + 消息数与相对时间 */
function SessionItem({
  session,
  active,
  onSwitch,
  onRename,
}: {
  session: SessionDTO;
  active: boolean;
  onSwitch: (sid: string) => void;
  onRename: (s: SessionDTO) => void;
}) {
  const title = session.title || `${session.session_id.slice(0, 8)}…`;
  return (
    <div
      className={cn(
        'group mb-0.5 cursor-pointer rounded-lg px-3 py-2 transition-colors',
        active ? 'bg-indigo-50' : 'hover:bg-zinc-100',
      )}
      onClick={() => onSwitch(session.session_id)}
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
              onRename(session);
            }}
          >
            <Pencil size={12} />
          </button>
          <button
            className="icon-btn h-6 w-6 hover:text-red-500"
            title="删除"
            onClick={e => {
              e.stopPropagation();
              void removeSession(session.session_id);
            }}
          >
            <Trash2 size={12} />
          </button>
        </span>
      </div>
      <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-zinc-400">
        <span>{session.message_count} 条消息</span>
        <span>·</span>
        <span>{formatRelativeTime(session.updated_at)}</span>
      </div>
    </div>
  );
}

/** 分组标题行：与主导航项（记忆/技能/模型）平级同样式，标题点击折叠，右侧 + 号新建 */
function GroupHeader({
  label,
  open,
  onToggle,
  onAdd,
  addTitle,
}: {
  label: string;
  open: boolean;
  onToggle: () => void;
  onAdd: () => void;
  addTitle: string;
}) {
  return (
    <div className="group flex shrink-0 items-center gap-1 rounded-lg transition-colors hover:bg-zinc-100">
      <button
        className="flex min-w-0 flex-1 cursor-pointer items-center gap-2.5 px-3 py-2 text-[13px] font-medium text-zinc-500 transition-colors hover:text-zinc-800"
        onClick={onToggle}
      >
        <ChevronDown
          size={16}
          className={cn('shrink-0 transition-transform', !open && '-rotate-90')}
        />
        {label}
      </button>
      <button
        className="icon-btn mr-1 h-6 w-6 shrink-0 hover:text-indigo-600"
        title={addTitle}
        onClick={onAdd}
      >
        <Plus size={14} />
      </button>
    </div>
  );
}

export default function Sidebar() {
  const navigate = useNavigate();
  const sessions = useAppStore(s => s.sessions);
  const currentSessionId = useAppStore(s => s.currentSessionId);
  const projects = useAppStore(s => s.projects);
  const [chatsOpen, setChatsOpen] = useState(() => readOpenFlag(CHATS_OPEN_KEY));
  const [projectsOpen, setProjectsOpen] = useState(() => readOpenFlag(PROJECTS_OPEN_KEY));
  const [collapsedProjects, setCollapsedProjects] = useState<Record<string, boolean>>(readCollapsedProjects);
  const [renaming, setRenaming] = useState<SessionDTO | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [manageOpen, setManageOpen] = useState(false);

  const chatSessions = useMemo(() => sessions.filter(s => !s.project_id), [sessions]);
  const projectSessions = useMemo(() => {
    const map = new Map<string, SessionDTO[]>();
    for (const s of sessions) {
      if (!s.project_id) continue;
      const list = map.get(s.project_id) ?? [];
      list.push(s);
      map.set(s.project_id, list);
    }
    return map;
  }, [sessions]);

  const toggleChats = () => {
    setChatsOpen(prev => {
      localStorage.setItem(CHATS_OPEN_KEY, prev ? '0' : '1');
      return !prev;
    });
  };

  const toggleProjects = () => {
    setProjectsOpen(prev => {
      localStorage.setItem(PROJECTS_OPEN_KEY, prev ? '0' : '1');
      return !prev;
    });
  };

  const toggleProject = (projectId: string) => {
    setCollapsedProjects(prev => {
      const next = { ...prev, [projectId]: !prev[projectId] };
      localStorage.setItem(PROJECT_COLLAPSED_KEY, JSON.stringify(next));
      return next;
    });
  };

  const handleSwitch = (sid: string) => {
    void switchSession(sid);
    navigate('/');
  };

  /** 新建会话（projectId 为 '' 时即普通聊天），首个消息发送时后端才真正创建 */
  const handleNewIn = (projectId: string) => {
    newSessionInProject(projectId);
    navigate('/');
  };

  const openRename = (s: SessionDTO) => {
    setRenameValue(s.title);
    setRenaming(s);
  };

  const confirmRename = async () => {
    if (!renaming) return;
    const title = renameValue.trim();
    setRenaming(null);
    if (title && title !== renaming.title) {
      await renameSessionAction(renaming.session_id, title);
    }
  };

  const renderSessions = (list: SessionDTO[]) =>
    list.map(s => (
      <SessionItem
        key={s.session_id}
        session={s}
        active={s.session_id === currentSessionId}
        onSwitch={handleSwitch}
        onRename={openRename}
      />
    ));

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

      {/* 新建会话（普通聊天，不归属项目） */}
      <div className="px-3 pb-2">
        <button className="btn btn-primary w-full" onClick={() => handleNewIn('')}>
          <MessageSquarePlus size={16} />
          新建会话
        </button>
      </div>

      {/* 导航 + 会话树（聊天/项目分组与主导航平级；分组列表过长时内部滚动，不把后续栏目挤出视口） */}
      <nav className="flex min-h-0 flex-1 flex-col px-2 pb-2">
        {NAV_ITEMS.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                'flex shrink-0 items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] font-medium transition-colors',
                isActive ? 'bg-indigo-50 text-indigo-700' : 'text-zinc-500 hover:bg-zinc-100 hover:text-zinc-800',
              )
            }
          >
            <Icon size={16} />
            {label}
          </NavLink>
        ))}

        <GroupHeader
          label="聊天"
          open={chatsOpen}
          onToggle={() => {
            toggleChats();
            navigate('/');
          }}
          onAdd={() => handleNewIn('')}
          addTitle="新建会话（普通聊天）"
        />
        {chatsOpen && (
          <div className="nice-scroll mb-1 min-h-0 flex-[2_1_0%] overflow-y-auto pr-0.5">
            {chatSessions.length === 0 ? (
              <div className="ml-3 px-3 py-2 text-xs text-zinc-400">暂无会话，点击 + 开始</div>
            ) : (
              <div className="ml-3 pr-1">{renderSessions(chatSessions)}</div>
            )}
          </div>
        )}

        <GroupHeader
          label="项目"
          open={projectsOpen}
          onToggle={toggleProjects}
          onAdd={() => setManageOpen(true)}
          addTitle="新建项目"
        />
        {projectsOpen && (
          <div className="nice-scroll min-h-0 flex-1 overflow-y-auto pr-0.5">
            {projects.length === 0 ? (
              <div className="ml-3 px-3 py-2 text-xs text-zinc-400">暂无项目，点击 + 新建</div>
            ) : (
              projects.map(p => {
                const list = projectSessions.get(p.project_id) ?? [];
                const expanded = !collapsedProjects[p.project_id];
                return (
                  <div key={p.project_id} className="ml-3">
                    <div className="group flex items-center gap-1 rounded-lg transition-colors hover:bg-zinc-100">
                      <button
                        className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 px-2.5 py-2 text-left text-[13px] font-medium text-zinc-600 transition-colors hover:text-zinc-800"
                        onClick={() => toggleProject(p.project_id)}
                        title={p.work_dir}
                      >
                        {list.length > 0 ? (
                          <ChevronDown
                            size={14}
                            className={cn('shrink-0 text-zinc-400 transition-transform', !expanded && '-rotate-90')}
                          />
                        ) : (
                          <span className="w-3.5 shrink-0" />
                        )}
                        <FolderOpen size={15} className="shrink-0 text-indigo-500" />
                        <span className="truncate">{p.name}</span>
                      </button>
                      <button
                        className="icon-btn mr-1 h-6 w-6 shrink-0 hover:text-indigo-600"
                        title={`在「${p.name}」中新建会话`}
                        onClick={() => handleNewIn(p.project_id)}
                      >
                        <Plus size={14} />
                      </button>
                    </div>
                    {expanded && list.length > 0 && (
                      <div className="ml-4 pr-1">{renderSessions(list)}</div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        )}
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

      {/* 新建项目弹窗（直达创建表单） */}
      <ProjectManagerDialog open={manageOpen} initialMode="create" onClose={() => setManageOpen(false)} />
    </aside>
  );
}
