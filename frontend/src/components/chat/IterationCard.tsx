import { useState } from 'react';
import { Repeat2 } from 'lucide-react';
import type { IterationBlockView } from '../../types';
import { useChatStore } from '../../stores/chatStore';

/** 迭代上限审批：停止 / 继续一轮 / 继续并提高上限 */
export default function IterationCard({ turnId, block }: { turnId: string; block: IterationBlockView }) {
  const decideIterationBlock = useChatStore(s => s.decideIterationBlock);
  const [raise, setRaise] = useState(5);

  const decide = (approved: boolean, raiseBy?: number) => {
    void decideIterationBlock(turnId, block.id, approved, raiseBy);
  };

  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50/60">
      <div className="flex items-center gap-2 px-3 py-2 text-xs text-amber-700">
        <Repeat2 size={14} className="shrink-0" />
        <span className="font-medium">已达到迭代上限（{block.current}/{block.max}），是否继续？</span>
      </div>
      {block.decision ? (
        <div className="border-t border-amber-200 bg-amber-50/80 px-3 py-2 text-[11px] font-medium text-amber-700">
          {block.decision.approved
            ? `✓ 已继续${block.decision.raisedBy ? `（上限 +${block.decision.raisedBy}）` : ''}`
            : '✗ 已停止'}
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2 border-t border-amber-200 bg-amber-50/80 px-3 py-2.5">
          <button className="btn btn-danger-soft px-2.5 py-1 text-xs" onClick={() => decide(false)}>
            停止
          </button>
          <button className="btn btn-success-soft px-2.5 py-1 text-xs" onClick={() => decide(true)}>
            继续一轮
          </button>
          <span className="ml-1 flex items-center gap-1.5">
            <input
              type="number"
              min={1}
              className="w-14 rounded-md border border-amber-300 bg-white px-1.5 py-1 text-xs outline-none focus:border-amber-400"
              value={raise}
              onChange={e => setRaise(Math.max(1, Number(e.target.value) || 1))}
            />
            <button
              className="btn btn-success-soft px-2.5 py-1 text-xs"
              title="继续执行，并将迭代上限提高指定轮数"
              onClick={() => decide(true, raise)}
            >
              继续并提高上限
            </button>
          </span>
        </div>
      )}
    </div>
  );
}
