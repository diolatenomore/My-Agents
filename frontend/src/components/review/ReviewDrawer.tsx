import { FileCheck2, X } from 'lucide-react';
import { useReviewStore } from '../../stores/reviewStore';
import { confirmDialog } from '../../stores/uiStore';
import ReviewNode from './ReviewNode';
import EmptyState from '../common/EmptyState';

/** 右侧抽屉：VFS 文件变更审批树（有待审批项时自动展开） */
export default function ReviewDrawer() {
  const open = useReviewStore(s => s.open);
  const tree = useReviewStore(s => s.tree);
  const setOpen = useReviewStore(s => s.setOpen);
  const decideAll = useReviewStore(s => s.decideAll);

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
      <div className="flex h-14 shrink-0 items-center justify-between border-b border-zinc-200 px-4">
        <div className="flex items-center gap-2">
          <FileCheck2 size={16} className="text-amber-500" />
          <span className="text-sm font-semibold text-zinc-800">文件变更审批</span>
          {tree && (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-700">
              {tree.items.length} 项
            </span>
          )}
        </div>
        <button className="icon-btn" onClick={() => setOpen(false)} aria-label="关闭审批面板">
          <X size={16} />
        </button>
      </div>

      {tree ? (
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
