import { CheckCircle2, Circle, CircleDot, CircleX, ListTodo } from 'lucide-react';
import { useTodoStore } from '../../stores/todoStore';
import { cn } from '../../utils/misc';
import EmptyState from '../common/EmptyState';
import type { TodoStatus } from '../../types';

const STATUS_META: Record<TodoStatus, { icon: typeof Circle; className: string; label: string }> = {
  pending: { icon: Circle, className: 'text-zinc-400', label: '待办' },
  in_progress: { icon: CircleDot, className: 'text-indigo-500', label: '进行中' },
  completed: { icon: CheckCircle2, className: 'text-emerald-500', label: '已完成' },
  cancelled: { icon: CircleX, className: 'text-zinc-400', label: '已取消' },
};

/** 任务清单面板：数据来自 todo 工具结果（SSE 实时 / 会话历史恢复） */
export default function TodoPanel() {
  const todos = useTodoStore(s => s.todos);
  const summary = useTodoStore(s => s.summary);

  if (todos.length === 0) {
    return (
      <EmptyState
        icon={ListTodo}
        title="暂无任务清单"
        description="让 Agent 使用 todo 工具规划任务后，清单会实时显示在这里"
      />
    );
  }

  const done = todos.filter(t => t.status === 'completed').length;
  const pct = Math.round((done / todos.length) * 100);

  return (
    <div className="flex h-full flex-col">
      {/* 进度概览 */}
      <div className="shrink-0 border-b border-zinc-100 px-4 py-3">
        {summary && <div className="text-xs leading-relaxed text-zinc-500">{summary}</div>}
        <div className="mt-2 flex items-center gap-2">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-zinc-100">
            <div
              className="h-full rounded-full bg-emerald-500 transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="text-[11px] font-medium text-zinc-400">
            {done}/{todos.length}
          </span>
        </div>
      </div>

      <div className="nice-scroll min-h-0 flex-1 overflow-y-auto p-2">
        {todos.map(t => {
          const status: TodoStatus = t.status ?? 'pending';
          const meta = STATUS_META[status] ?? STATUS_META.pending;
          const Icon = meta.icon;
          const dimmed = status === 'completed' || status === 'cancelled';
          return (
            <div key={t.id} className="flex items-start gap-2.5 rounded-lg px-2 py-2 hover:bg-zinc-50">
              <Icon size={15} className={cn('mt-0.5 shrink-0', meta.className)} />
              <div className="min-w-0 flex-1">
                <div
                  className={cn(
                    'text-[13px] leading-relaxed break-words',
                    dimmed ? 'text-zinc-400 line-through' : 'text-zinc-700',
                  )}
                >
                  {t.text}
                </div>
              </div>
              <span className={cn('shrink-0 text-[10px]', meta.className)}>{meta.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
