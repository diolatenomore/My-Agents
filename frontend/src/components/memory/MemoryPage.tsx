import { useCallback, useEffect, useState } from 'react';
import { Brain, ChevronLeft, ChevronRight, KeyRound, Pencil, RefreshCw, Trash2 } from 'lucide-react';
import type { MemoryItem, MemoryType } from '../../types';
import { deleteMemory, listMemories, updateMemory } from '../../api/memories';
import { confirmDialog, toast } from '../../stores/uiStore';
import { cn, formatDateTime } from '../../utils/misc';
import PageHeader from '../common/PageHeader';
import EmptyState from '../common/EmptyState';
import Modal from '../common/Modal';

const PAGE_SIZE = 20;

const TYPE_LABEL: Record<MemoryType, string> = {
  preference: '偏好',
  semantic: '事实',
};

export default function MemoryPage() {
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [type, setType] = useState<'' | MemoryType>('');
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<MemoryItem | null>(null);
  const [editValue, setEditValue] = useState('');
  const [editKey, setEditKey] = useState('');

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listMemories({
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
        memoryType: type || undefined,
      });
      setItems(data.items);
      setTotal(data.total);
    } catch (err) {
      toast('error', err instanceof Error ? err.message : '加载记忆失败');
    } finally {
      setLoading(false);
    }
  }, [page, type]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleTypeChange = (t: '' | MemoryType) => {
    setType(t);
    setPage(1);
  };

  const openEdit = (m: MemoryItem) => {
    setEditing(m);
    setEditValue(m.value);
    setEditKey(m.key);
  };

  const saveEdit = async () => {
    if (!editing) return;
    const value = editValue.trim();
    if (!value) {
      toast('error', '内容不能为空');
      return;
    }
    try {
      const res = await updateMemory(editing.id, { value, key: editKey.trim() });
      if (res.code === 200) {
        toast('success', '记忆已更新');
        setEditing(null);
        await load();
      } else {
        toast('error', res.message || '更新失败');
      }
    } catch (err) {
      toast('error', err instanceof Error ? err.message : '更新失败');
    }
  };

  const handleDelete = async (m: MemoryItem) => {
    const ok = await confirmDialog({
      title: '删除记忆',
      message: '确定删除这条记忆？删除后不可恢复。',
      confirmText: '删除',
      danger: true,
    });
    if (!ok) return;
    try {
      const res = await deleteMemory(m.id);
      if (res.code === 200) {
        toast('success', '已删除');
        await load();
      } else {
        toast('error', res.message || '删除失败');
      }
    } catch (err) {
      toast('error', err instanceof Error ? err.message : '删除失败');
    }
  };

  return (
    <div className="nice-scroll min-h-0 flex-1 overflow-y-auto bg-zinc-50">
      <div className="mx-auto w-full max-w-4xl px-6 py-6">
        <PageHeader
          icon={Brain}
          title="记忆管理"
          subtitle={total > 0 ? `共 ${total} 条长期记忆` : 'Agent 会自动从对话中提取偏好与事实'}
          actions={
            <>
              <select
                className="input w-32 py-1.5 text-[13px]"
                value={type}
                onChange={e => handleTypeChange(e.target.value as '' | MemoryType)}
              >
                <option value="">全部类型</option>
                <option value="preference">偏好 preference</option>
                <option value="semantic">事实 semantic</option>
              </select>
              <button className="btn btn-outline" onClick={() => void load()} title="刷新">
                <RefreshCw size={14} className={cn(loading && 'animate-spin')} />
                刷新
              </button>
            </>
          }
        />

        <div className="space-y-2">
          {items.length === 0 ? (
            <EmptyState
              icon={Brain}
              title={loading ? '加载中…' : '暂无记忆'}
              description={loading ? undefined : '多和 Agent 聊聊，它会记住你的偏好和重要事实'}
            />
          ) : (
            items.map(m => (
              <div key={m.id} className="card group flex items-start gap-3 px-4 py-3">
                <span
                  className={cn(
                    'mt-0.5 shrink-0 rounded-md px-2 py-0.5 text-[11px] font-medium',
                    m.memory_type === 'preference'
                      ? 'bg-indigo-50 text-indigo-600'
                      : 'bg-sky-50 text-sky-600',
                  )}
                >
                  {TYPE_LABEL[m.memory_type] ?? m.memory_type}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-sm leading-relaxed break-words text-zinc-700">{m.value}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-zinc-400">
                    {m.memory_type === 'preference' && m.key && (
                      <span className="inline-flex items-center gap-1 rounded bg-zinc-100 px-1.5 py-0.5 font-mono">
                        <KeyRound size={10} />
                        {m.key}
                      </span>
                    )}
                    <span>{formatDateTime(m.created_at)}</span>
                  </div>
                </div>
                <span className="flex shrink-0 items-center gap-1">
                  <button className="icon-btn" title="编辑" onClick={() => openEdit(m)}>
                    <Pencil size={13} />
                  </button>
                  <button
                    className="icon-btn hover:text-red-500"
                    title="删除"
                    onClick={() => void handleDelete(m)}
                  >
                    <Trash2 size={13} />
                  </button>
                </span>
              </div>
            ))
          )}
        </div>

        {/* 分页 */}
        {total > PAGE_SIZE && (
          <div className="mt-4 flex items-center justify-between text-xs text-zinc-500">
            <span>
              共 {total} 条 · 第 {page}/{totalPages} 页
            </span>
            <div className="flex gap-2">
              <button
                className="btn btn-outline px-2 py-1"
                disabled={page <= 1}
                onClick={() => setPage(p => p - 1)}
              >
                <ChevronLeft size={14} />
                上一页
              </button>
              <button
                className="btn btn-outline px-2 py-1"
                disabled={page >= totalPages}
                onClick={() => setPage(p => p + 1)}
              >
                下一页
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* 编辑弹窗 */}
      <Modal
        open={editing !== null}
        title="编辑记忆"
        onClose={() => setEditing(null)}
        footer={
          <>
            <button className="btn btn-outline" onClick={() => setEditing(null)}>
              取消
            </button>
            <button className="btn btn-primary" onClick={() => void saveEdit()}>
              保存
            </button>
          </>
        }
      >
        <div className="space-y-3">
          {editing?.memory_type === 'preference' && (
            <div>
              <label className="mb-1 block text-xs font-medium text-zinc-500">Key（仅偏好类记忆）</label>
              <input
                className="input font-mono text-[13px]"
                value={editKey}
                onChange={e => setEditKey(e.target.value)}
                placeholder="如 language、response_style"
              />
            </div>
          )}
          <div>
            <label className="mb-1 block text-xs font-medium text-zinc-500">内容</label>
            <textarea
              className="input min-h-24 resize-y"
              value={editValue}
              onChange={e => setEditValue(e.target.value)}
            />
          </div>
        </div>
      </Modal>
    </div>
  );
}
