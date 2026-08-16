import { useState } from 'react';
import { CheckCircle2, ChevronDown, Circle, CircleDot, CircleX, ListTodo } from 'lucide-react';
import { useTodoStore } from '../../stores/todoStore';
import { cn } from '../../utils/misc';
import type { TodoStatus } from '../../types';

const STATUS_META: Record<TodoStatus, { icon: typeof Circle; className: string; label: string }> = {
  pending: { icon: Circle, className: 'text-zinc-400', label: '待办' },
  in_progress: { icon: CircleDot, className: 'text-indigo-500', label: '进行中' },
  completed: { icon: CheckCircle2, className: 'text-emerald-500', label: '已完成' },
  cancelled: { icon: CircleX, className: 'text-zinc-400', label: '已取消' },
};

/** 输入框上方的任务清单条：有任务时常驻显示，点击标题可折叠，无任务时不占位 */
export default function TodoBar() {
  const todos = useTodoStore(s => s.todos);
  const [collapsed, setCollapsed] = useState(false);

  if (todos.length === 0) return null;

  const done = todos.filter(t => (t.status ?? 'pending') === 'completed').length;
  const pct = Math.round((done / todos.length) * 100);
  const active = todos.find(t => t.status === 'in_progress');

  return (
    <div className="mb-2 rounded-xl border border-zinc-200 bg-white shadow-sm">
      <button
        className="flex w-full cursor-pointer items-center gap-2 px-3.5 py-2"
        onClick={() => setCollapsed(!collapsed)}
      >
        <ListTodo size={14} className="shrink-0 text-indigo-500" />
        <span className="shrink-0 text-xs font-semibold text-zinc-700">任务清单</span>
        <span className="h-1.5 w-20 shrink-0 overflow-hidden rounded-full bg-zinc-100">
          <span
            className="block h-full rounded-full bg-emerald-500 transition-all"
            style={{ width: `${pct}%` }}
          />
        </span>
        <span className="shrink-0 text-[11px] font-medium text-zinc-400">
          {done}/{todos.length}
        </span>
        {collapsed && active && (
          <span className="min-w-0 truncate text-[11px] text-indigo-500">进行中：{active.text}</span>
        )}
        <ChevronDown
          size={14}
          className={cn('ml-auto shrink-0 text-zinc-400 transition-transform', collapsed && '-rotate-90')}
        />
      </button>
      {!collapsed && (
        <div className="nice-scroll max-h-44 overflow-y-auto border-t border-zinc-100 px-3.5 py-1.5">
          {todos.map(t => {
            const status: TodoStatus = t.status ?? 'pending';
            const meta = STATUS_META[status] ?? STATUS_META.pending;
            const Icon = meta.icon;
            const dimmed = status === 'completed' || status === 'cancelled';
            return (
              <div key={t.id} className="flex items-center gap-2 py-1">
                <Icon size={13} className={cn('shrink-0', meta.className)} />
                <span
                  className={cn(
                    'min-w-0 flex-1 truncate text-xs leading-relaxed',
                    dimmed ? 'text-zinc-400 line-through' : 'text-zinc-700',
                  )}
                >
                  {t.text}
                </span>
                <span className={cn('shrink-0 text-[10px]', meta.className)}>{meta.label}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
