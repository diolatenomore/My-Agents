import { FileCheck2, ListTodo, X } from 'lucide-react';
import { useReviewStore } from '../../stores/reviewStore';
import { useTodoStore } from '../../stores/todoStore';
import { confirmDialog } from '../../stores/uiStore';
import { cn } from '../../utils/misc';
import ReviewNode from './ReviewNode';
import TodoPanel from '../todo/TodoPanel';
import EmptyState from '../common/EmptyState';

/** 右侧抽屉：文件变更审批 + 任务清单（todo）双面板 */
export default function ReviewDrawer() {
  const open = useReviewStore(s => s.open);
  const tab = useReviewStore(s => s.tab);
  const setTab = useReviewStore(s => s.setTab);
  const setOpen = useReviewStore(s => s.setOpen);
  const tree = useReviewStore(s => s.tree);
  const decideAll = useReviewStore(s => s.decideAll);
  const todoCount = useTodoStore(s => s.todos.length);

  if (!open) return null;

  const handleAll = async (approved: boolean) => {
    const action = approved ? '通过' : '拒绝';
    const ok = await confirmDialog({
      title: `${action}全部变更`,
      message: `确定${action}全部文件变更？`,
      confirmText: action,
      danger: !approved,
    });
    if (ok) await decideAll(approved);
  };

  return (
    <aside className="drawer-in flex w-96 shrink-0 flex-col border-l border-zinc-200 bg-white">
      {/* 头部：双 Tab + 关闭 */}
      <div className="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-zinc-200 px-4">
        <div className="flex items-center gap-1">
          <button
            className={cn(
              'flex cursor-pointer items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[13px] font-medium transition-colors',
              tab === 'review' ? 'bg-zinc-100 text-zinc-800' : 'text-zinc-500 hover:text-zinc-700',
            )}
            onClick={() => setTab('review')}
          >
            <FileCheck2 size={14} className={tree ? 'text-amber-500' : undefined} />
            文件审批
            {tree && (
              <span className="rounded-full bg-amber-100 px-1.5 text-[10px] font-medium text-amber-700">
                {tree.items.length}
              </span>
            )}
          </button>
          <button
            className={cn(
              'flex cursor-pointer items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[13px] font-medium transition-colors',
              tab === 'todo' ? 'bg-zinc-100 text-zinc-800' : 'text-zinc-500 hover:text-zinc-700',
            )}
            onClick={() => setTab('todo')}
          >
            <ListTodo size={14} />
            任务清单
            {todoCount > 0 && (
              <span className="rounded-full bg-indigo-100 px-1.5 text-[10px] font-medium text-indigo-600">
                {todoCount}
              </span>
            )}
          </button>
        </div>
        <button className="icon-btn" onClick={() => setOpen(false)} aria-label="关闭面板">
          <X size={16} />
        </button>
      </div>

      {tab === 'todo' ? (
        <TodoPanel />
      ) : tree ? (
        <>
          <div className="flex shrink-0 gap-2 border-b border-zinc-100 px-4 py-2.5">
            <button className="btn btn-success-soft flex-1 text-xs" onClick={() => void handleAll(true)}>
              全部通过
            </button>
            <button className="btn btn-danger-soft flex-1 text-xs" onClick={() => void handleAll(false)}>
              全部拒绝
            </button>
          </div>
          <div className="nice-scroll min-h-0 flex-1 overflow-y-auto p-2">
            {tree.items.map(item => (
              <ReviewNode key={item.id} node={item} depth={0} />
            ))}
          </div>
        </>
      ) : (
        <EmptyState
          icon={FileCheck2}
          title="没有待审批的文件变更"
          description="Agent 修改文件后，变更会出现在这里等待审批"
        />
      )}
    </aside>
  );
}
