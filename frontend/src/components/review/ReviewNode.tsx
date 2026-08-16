import {
  Check,
  FileMinus2,
  FilePenLine,
  FilePlus2,
  FileSymlink,
  FolderMinus,
  FolderPlus,
  FolderSync,
  X,
  type LucideIcon,
} from 'lucide-react';
import type { ReviewItem, VfsOpType } from '../../types';
import { useReviewStore } from '../../stores/reviewStore';

const OP_META: Record<VfsOpType, { label: string; icon: LucideIcon; tone: string }> = {
  MKDIR: { label: '创建目录', icon: FolderPlus, tone: 'text-sky-500' },
  DELETE_DIR: { label: '删除目录', icon: FolderMinus, tone: 'text-red-500' },
  RENAME_DIR: { label: '重命名目录', icon: FolderSync, tone: 'text-amber-500' },
  CREATE_FILE: { label: '新建文件', icon: FilePlus2, tone: 'text-sky-500' },
  DELETE_FILE: { label: '删除文件', icon: FileMinus2, tone: 'text-red-500' },
  MODIFY_FILE: { label: '修改文件', icon: FilePenLine, tone: 'text-amber-500' },
  RENAME_FILE: { label: '重命名文件', icon: FileSymlink, tone: 'text-amber-500' },
};

export default function ReviewNode({ node, depth }: { node: ReviewItem; depth: number }) {
  const decideItem = useReviewStore(s => s.decideItem);
  const meta = OP_META[node.op_type] ?? { label: node.op_type, icon: FilePenLine, tone: 'text-zinc-400' };
  const Icon = meta.icon;

  return (
    <>
      <div
        className="group flex items-start gap-2 rounded-lg px-2 py-2 hover:bg-zinc-50"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        <Icon size={14} className={`mt-0.5 shrink-0 ${meta.tone}`} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="shrink-0 text-[11px] font-medium text-zinc-500">{meta.label}</span>
            {node.status && node.status !== 'pending' && (
              <span className="rounded bg-zinc-100 px-1.5 py-px text-[10px] text-zinc-500">
                {node.status}
              </span>
            )}
          </div>
          <div className="mt-0.5 font-mono text-[11px] leading-relaxed break-all text-zinc-700">
            {node.source}
            {node.target ? <span className="text-zinc-400"> → {node.target}</span> : null}
            {node.copy_source ? (
              <span className="text-zinc-400">（来源: {node.copy_source}）</span>
            ) : null}
          </div>
        </div>
        <span className="flex shrink-0 items-center gap-1">
          <button
            className="icon-btn h-6 w-6 hover:text-emerald-600"
            title="通过"
            onClick={() => void decideItem(node.id, true)}
          >
            <Check size={13} />
          </button>
          <button
            className="icon-btn h-6 w-6 hover:text-red-500"
            title="拒绝"
            onClick={() => void decideItem(node.id, false)}
          >
            <X size={13} />
          </button>
        </span>
      </div>
      {node.children?.map(child => (
        <ReviewNode key={child.id} node={child} depth={depth + 1} />
      ))}
    </>
  );
}
