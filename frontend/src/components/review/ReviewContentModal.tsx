import { useEffect, useState } from 'react';
import Modal from '../common/Modal';
import { getReviewItemContent } from '../../api/review';
import type { ReviewContent, ReviewItem } from '../../types';
import { useReviewStore } from '../../stores/reviewStore';
import { useAppStore } from '../../stores/appStore';

/** 单条文件变更的内容预览弹窗：新建/删除显示纯文本，修改显示 diff 高亮 */
export default function ReviewContentModal({
  item,
  onClose,
}: {
  item: ReviewItem;
  onClose: () => void;
}) {
  const [content, setContent] = useState<ReviewContent | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    const taskId =
      useReviewStore.getState().tree?.task_id || useAppStore.getState().currentSessionId;
    setLoading(true);
    setError('');
    getReviewItemContent(taskId, item.id)
      .then(res => {
        if (!alive) return;
        if (res.code === 200 && res.content) setContent(res.content);
        else setError(res.message || '无法读取文件内容');
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setError(e instanceof Error ? e.message : '加载失败');
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [item.id]);

  const renderBody = () => {
    if (loading)
      return <div className="py-8 text-center text-sm text-zinc-400">加载中…</div>;
    if (error)
      return <div className="py-8 text-center text-sm text-red-500">{error}</div>;
    if (!content) return null;

    // 修改操作：展示 diff 高亮
    if (content.diff) {
      return (
        <pre className="overflow-x-auto font-mono text-xs leading-relaxed">
          {content.diff.map((line, i) => (
            <div
              key={i}
              className={
                line.type === 'add'
                  ? 'bg-emerald-50 text-emerald-800'
                  : line.type === 'del'
                    ? 'bg-red-50 text-red-700'
                    : 'text-zinc-700'
              }
            >
              <span className="mr-2 inline-block w-4 select-none text-right text-zinc-400">
                {line.type === 'add' ? '+' : line.type === 'del' ? '-' : ' '}
              </span>
              {line.text || ' '}
            </div>
          ))}
        </pre>
      );
    }

    // 新建/删除：展示目标内容（新建=after，删除=before）
    const text = item.op_type === 'DELETE_FILE' ? content.before : content.after;
    return (
      <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-xs leading-relaxed text-zinc-700">
        {text?.length ? text : '（空文件）'}
      </pre>
    );
  };

  return (
    <Modal open onClose={onClose} title={item.source} width="max-w-4xl">
      {renderBody()}
    </Modal>
  );
}