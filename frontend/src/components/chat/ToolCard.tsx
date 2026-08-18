import { useMemo, useState } from 'react';
import { CheckCircle2, ChevronRight, Eye, Loader2, ShieldAlert, Wrench } from 'lucide-react';
import type { StoredMessage, ToolBlockView } from '../../types';
import { buildEntriesFromHistory, useChatStore } from '../../stores/chatStore';
import { useAppStore } from '../../stores/appStore';
import { getSubagentMessages } from '../../api/sessions';
import { cn, stringifyMaybeJson } from '../../utils/misc';
import TurnView from './TurnView';

/** 子 Agent 消息渲染：复用 buildEntriesFromHistory 将工具调用与结果按 tool_call_id 配对 */
function SubagentMessages({ messages }: { messages: StoredMessage[] }) {
  const entries = useMemo(() => buildEntriesFromHistory(messages), [messages]);
  return (
    <div className="max-h-96 overflow-auto space-y-2">
      {entries.map(entry => {
        if (entry.kind === 'turn') {
          return <TurnView key={entry.id} turn={entry} />;
        }
        // user 消息（子 Agent 的任务描述）
        return (
          <div
            key={entry.id}
            className="rounded bg-blue-50 px-2 py-1 text-[11px] text-blue-800 whitespace-pre-wrap break-words"
          >
            {entry.content}
          </div>
        );
      })}
    </div>
  );
}

/** 工具调用卡片：参数/结果可展开查看全文；需审批时展示审批按钮（普通 / 达到调用上限两种） */
export default function ToolCard({ turnId, block }: { turnId: string; block: ToolBlockView }) {
  const decideToolBlock = useChatStore(s => s.decideToolBlock);
  const currentSessionId = useAppStore(s => s.currentSessionId);
  const [open, setOpen] = useState(false);
  const [raise, setRaise] = useState(5);
  const [subagentOpen, setSubagentOpen] = useState(false);
  const [subagentLoading, setSubagentLoading] = useState(false);
  const [subagentMessages, setSubagentMessages] = useState<StoredMessage[] | null>(null);

  const awaiting = block.status === 'awaiting' && !block.decision;
  const resultText = block.result != null ? stringifyMaybeJson(block.result) : '';
  const argsText = stringifyMaybeJson(block.args);
  const hasDetail = argsText !== '' || resultText !== '';
  const isDelegateTask = block.name === 'delegate_task';

  const decide = (approved: boolean, raiseBy?: number) => {
    void decideToolBlock(turnId, block.id, approved, raiseBy);
  };

  const loadSubagentHistory = async () => {
    if (subagentOpen) {
      setSubagentOpen(false);
      return;
    }
    if (subagentMessages) {
      setSubagentOpen(true);
      return;
    }
    setSubagentLoading(true);
    try {
      const data = await getSubagentMessages(currentSessionId || '', block.toolCallId || '');
      setSubagentMessages(data.messages);
      setSubagentOpen(true);
    } catch {
      setSubagentMessages([]);
    } finally {
      setSubagentLoading(false);
    }
  };

  return (
    <div
      className={cn(
        'overflow-hidden rounded-lg border',
        awaiting ? 'border-amber-300 bg-amber-50/60' : 'border-zinc-200 bg-white',
      )}
    >
      {/* 头部：状态图标 + 工具名 + 阈值信息 + 展开箭头 */}
      <button
        className="flex w-full cursor-pointer items-center gap-2 px-3 py-2 text-left"
        onClick={() => hasDetail && setOpen(!open)}
        disabled={!hasDetail}
      >
        {awaiting ? (
          <ShieldAlert size={14} className="shrink-0 text-amber-500" />
        ) : block.status === 'running' ? (
          <Loader2 size={14} className="shrink-0 animate-spin text-indigo-400" />
        ) : (
          <CheckCircle2 size={14} className="shrink-0 text-zinc-400" />
        )}
        <Wrench size={12} className="shrink-0 text-zinc-400" />
        <span className="shrink-0 font-mono text-xs font-medium text-zinc-700">{block.name}</span>
        {block.threshold && (
          <span className="shrink-0 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
            已达上限 {block.threshold.current}/{block.threshold.max}
          </span>
        )}
        {awaiting && (
          <span className="shrink-0 text-[11px] font-medium text-amber-600">待审批</span>
        )}
        {hasDetail && (
          <ChevronRight
            size={13}
            className={cn('ml-auto shrink-0 text-zinc-400 transition-transform', open && 'rotate-90')}
          />
        )}
      </button>

      {/* 详情：参数 + 结果全文 */}
      {open && hasDetail && (
        <div className="space-y-2 border-t border-zinc-200/70 px-3 py-2.5">
          {argsText !== '' && (
            <div>
              <div className="mb-1 text-[10px] font-medium tracking-wide text-zinc-400 uppercase">
                参数
              </div>
              <pre className="nice-scroll max-h-40 overflow-auto rounded bg-zinc-50 p-2 font-mono text-[11px] leading-relaxed break-all whitespace-pre-wrap text-zinc-600">
                {argsText}
              </pre>
            </div>
          )}
          {resultText !== '' && (
            <div>
              <div className="mb-1 text-[10px] font-medium tracking-wide text-zinc-400 uppercase">
                结果
              </div>
              <pre className="nice-scroll max-h-64 overflow-auto rounded bg-zinc-50 p-2 font-mono text-[11px] leading-relaxed break-all whitespace-pre-wrap text-zinc-600">
                {resultText}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* delegate_task：查看子智能体执行过程 */}
      {isDelegateTask && block.status === 'done' && block.toolCallId && (
        <div className="border-t border-zinc-200/70 px-3 py-2">
          <button
            className="flex items-center gap-1.5 text-[11px] font-medium text-indigo-600 hover:text-indigo-700 transition-colors"
            onClick={loadSubagentHistory}
            disabled={subagentLoading}
          >
            {subagentLoading ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <Eye size={12} />
            )}
            {subagentOpen ? '收起执行过程' : '查看子智能体执行过程'}
          </button>
          {subagentOpen && subagentMessages && (
            <div className="mt-2 rounded border border-indigo-100 bg-indigo-50/30 p-2">
              {subagentMessages.length === 0 ? (
                <div className="text-[11px] text-zinc-400">暂无执行记录</div>
              ) : (
                <SubagentMessages messages={subagentMessages} />
              )}
            </div>
          )}
        </div>
      )}

      {/* 审批操作 */}
      {awaiting ? (
        <div className="flex flex-wrap items-center gap-2 border-t border-amber-200 bg-amber-50/80 px-3 py-2.5">
          <span className="mr-1 text-[11px] text-amber-700">是否允许执行？</span>
          <button className="btn btn-danger-soft px-2.5 py-1 text-xs" onClick={() => decide(false)}>
            拒绝
          </button>
          <button className="btn btn-success-soft px-2.5 py-1 text-xs" onClick={() => decide(true)}>
            通过
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
              title="通过本次调用，并将工具调用上限提高指定次数"
              onClick={() => decide(true, raise)}
            >
              通过并提高上限
            </button>
          </span>
        </div>
      ) : block.decision ? (
        <div className="border-t border-zinc-100 bg-zinc-50/60 px-3 py-2 text-[11px] font-medium">
          {block.decision.approved ? (
            <span className="text-emerald-600">
              ✓ 已通过{block.decision.raisedBy ? `（上限 +${block.decision.raisedBy}）` : ''}
            </span>
          ) : (
            <span className="text-red-500">✗ 已拒绝</span>
          )}
        </div>
      ) : null}
    </div>
  );
}