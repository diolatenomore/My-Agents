import { create } from 'zustand';
import type {
  ChatEntry,
  SkillSegment,
  StoredMessage,
  StreamEvent,
  TurnBlockView,
  TurnEntry,
} from '../types';
import { joinSegments } from '../types';
import { cancelChat, streamChat } from '../api/chat';
import { decideTool } from '../api/tools';
import { getSessionMessages } from '../api/sessions';
import { uid } from '../utils/misc';
import { useAppStore } from './appStore';
import { useReviewStore } from './reviewStore';
import { useTodoStore } from './todoStore';
import { toast } from './uiStore';

function findTurn(entries: ChatEntry[], turnId: string): TurnEntry | undefined {
  return entries.find(e => e.kind === 'turn' && e.id === turnId) as TurnEntry | undefined;
}

function freezeBlocks(blocks: TurnBlockView[]): TurnBlockView[] {
  return blocks.map(b => (b.kind === 'thinking' ? { ...b, streaming: false } : b));
}

/** 把会话历史消息转换为前端渲染条目（user 消息 + assistant 轮次，工具结果按 tool_call_id 配对） */
export function buildEntriesFromHistory(messages: StoredMessage[]): ChatEntry[] {
  const entries: ChatEntry[] = [];
  for (let i = 0; i < messages.length; i++) {
    const m = messages[i];
    if (m.role === 'system') continue;

    if (m.role === 'user') {
      const segments = Array.isArray(m.content) ? m.content : undefined;
      entries.push({
        kind: 'user',
        id: uid(),
        content: segments
          ? joinSegments(segments)
          : typeof m.content === 'string'
            ? m.content
            : '',
        segments,
      });
      continue;
    }

    if (m.role === 'assistant') {
      const blocks: TurnBlockView[] = [];
      if (m.reasoning_content) {
        blocks.push({ kind: 'thinking', id: uid(), content: m.reasoning_content, streaming: false });
      }
      if (m.tool_calls?.length) {
        // 向前扫描配对的 tool 消息，建立 tool_call_id → result 映射
        const resultMap = new Map<string, string>();
        let j = i + 1;
        while (j < messages.length && messages[j].role === 'tool') {
          const t = messages[j];
          if (t.tool_call_id) {
            resultMap.set(
              t.tool_call_id,
              typeof t.content === 'string' ? t.content : JSON.stringify(t.content),
            );
          }
          j++;
        }
        for (const tc of m.tool_calls) {
          blocks.push({
            kind: 'tool',
            id: uid(),
            name: tc.name,
            args: tc.args,
            toolCallId: tc.id,
            status: 'done',
            result: resultMap.get(tc.id),
          });
        }
        i = j - 1;
      }
      if (typeof m.content === 'string' && m.content) {
        blocks.push({ kind: 'text', id: uid(), content: m.content });
      }
      if (blocks.length > 0) {
        entries.push({
          kind: 'turn',
          id: uid(),
          blocks,
          status: m.cancelled ? 'cancelled' : 'done',
        });
      }
      continue;
    }
    // 未被配对的 tool 消息不展示（与旧测试页一致）
  }
  return entries;
}

interface ChatState {
  entries: ChatEntry[];
  streaming: boolean;
  /** 流式过程中的状态提示（思考中…/正在输出…/调用工具 xxx…） */
  streamLabel: string;
  contextTokens: number;
  historyLoading: boolean;
  abortController: AbortController | null;
  send: (segments: SkillSegment[]) => Promise<void>;
  stop: () => Promise<void>;
  loadHistory: (sessionId: string) => Promise<void>;
  clearEntries: () => void;
  decideToolBlock: (
    turnId: string,
    blockId: string,
    approved: boolean,
    raiseBy?: number,
  ) => Promise<void>;
  decideIterationBlock: (
    turnId: string,
    blockId: string,
    approved: boolean,
    raiseBy?: number,
  ) => Promise<void>;
}

export const useChatStore = create<ChatState>((set, get) => {
  const mutateTurn = (turnId: string, fn: (t: TurnEntry) => TurnEntry) => {
    set(state => ({
      entries: state.entries.map(e => (e.kind === 'turn' && e.id === turnId ? fn(e) : e)),
    }));
  };

  const applyEvent = (turnId: string, ev: StreamEvent) => {
    switch (ev.type) {
      case 'session_ready': {
        useAppStore.getState().adoptSession(ev.session_id);
        break;
      }

      case 'thinking': {
        mutateTurn(turnId, t => {
          const blocks = [...t.blocks];
          const last = blocks[blocks.length - 1];
          if (last && last.kind === 'thinking') {
            blocks[blocks.length - 1] = {
              ...last,
              content: last.content + ev.content,
              streaming: true,
            };
          } else {
            blocks.push({ kind: 'thinking', id: uid(), content: ev.content, streaming: true });
          }
          return { ...t, blocks };
        });
        set({ streamLabel: '思考中…' });
        break;
      }

      case 'token': {
        mutateTurn(turnId, t => {
          let blocks = t.blocks;
          // 首个可见 token 到达 → 折叠思考块
          if (blocks.some(b => b.kind === 'thinking' && b.streaming)) {
            blocks = blocks.map(b => (b.kind === 'thinking' ? { ...b, streaming: false } : b));
          }
          const last = blocks[blocks.length - 1];
          if (last && last.kind === 'text') {
            const copy = [...blocks];
            copy[copy.length - 1] = { ...last, content: last.content + ev.content };
            blocks = copy;
          } else {
            blocks = [...blocks, { kind: 'text', id: uid(), content: ev.content }];
          }
          return { ...t, blocks };
        });
        set({ streamLabel: '正在输出…' });
        break;
      }

      case 'tool_call':
      case 'threshold_tool_call': {
        const isThreshold = ev.type === 'threshold_tool_call';
        const awaiting = ev.type === 'tool_call' && ev.requires_approval === true;
        mutateTurn(turnId, t => ({
          ...t,
          blocks: [
            ...t.blocks,
            {
              kind: 'tool',
              id: uid(),
              name: ev.name,
              args: ev.args,
              toolCallId: ev.tool_call_id,
              status: awaiting || isThreshold ? 'awaiting' : 'running',
              approvalKind: awaiting ? 'normal' : isThreshold ? 'threshold' : undefined,
              threshold: isThreshold
                ? { current: ev.current_tool_calls, max: ev.max_tool_calls }
                : undefined,
            },
          ],
        }));
        set({ streamLabel: `调用工具 ${ev.name}…` });
        break;
      }

      case 'threshold_iteration': {
        mutateTurn(turnId, t => ({
          ...t,
          blocks: [
            ...t.blocks,
            {
              kind: 'iteration',
              id: uid(),
              toolCallId: ev.tool_call_id,
              current: ev.current_iterations,
              max: ev.max_iterations,
            },
          ],
        }));
        set({ streamLabel: '等待确认是否继续…' });
        break;
      }

      case 'tool_result': {
        mutateTurn(turnId, t => {
          const blocks = [...t.blocks];
          // 按 tool_call_id 精确匹配
          for (let i = blocks.length - 1; i >= 0; i--) {
            const b = blocks[i];
            if (b.kind === 'tool' && b.toolCallId === ev.tool_call_id) {
              blocks[i] = { ...b, result: ev.result, status: 'done' };
              return { ...t, blocks };
            }
          }
          blocks.push({
            kind: 'tool',
            id: uid(),
            name: ev.name,
            args: {},
            toolCallId: ev.tool_call_id,
            status: 'done',
            result: ev.result,
          });
          return { ...t, blocks };
        });
        if (ev.name === 'todo') useTodoStore.getState().ingestResult(ev.result);
        set({ streamLabel: '思考中…' });
        break;
      }

      case 'done': {
        if (ev.context_tokens != null) set({ contextTokens: ev.context_tokens });
        const notes: string[] = [];
        if (ev.finish_reason === 'length') notes.push('输出达到上限，内容可能不完整');
        if (ev.stop_reason === 'max_iterations') notes.push('已达迭代上限');
        mutateTurn(turnId, t => ({
          ...t,
          status: 'done',
          note: notes.length > 0 ? notes.join('；') : undefined,
          blocks: freezeBlocks(t.blocks),
        }));
        if (ev.review_tree) useReviewStore.getState().present(ev.review_tree);
        break;
      }

      case 'cancelled': {
        if (ev.context_tokens != null) set({ contextTokens: ev.context_tokens });
        mutateTurn(turnId, t => ({ ...t, status: 'cancelled', blocks: freezeBlocks(t.blocks) }));
        if (ev.review_tree) useReviewStore.getState().present(ev.review_tree);
        break;
      }

      case 'error': {
        mutateTurn(turnId, t => ({
          ...t,
          status: 'error',
          blocks: [...freezeBlocks(t.blocks), { kind: 'error-note', id: uid(), message: ev.message }],
        }));
        break;
      }
    }
  };

  return {
    entries: [],
    streaming: false,
    streamLabel: '',
    contextTokens: 0,
    historyLoading: false,
    abortController: null,

    send: async segments => {
      const { streaming } = get();
      if (streaming) return;
      const app = useAppStore.getState();
      const turnId = uid();
      const controller = new AbortController();
      set(state => ({
        entries: [
          ...state.entries,
          { kind: 'user', id: uid(), content: joinSegments(segments), segments },
          { kind: 'turn', id: turnId, blocks: [], status: 'streaming' },
        ],
        streaming: true,
        streamLabel: '思考中…',
        abortController: controller,
      }));
      try {
        await streamChat(
          {
            segments,
            session_id: app.currentSessionId || undefined,
            model_id: app.selectedModelId || undefined,
            project_id: app.currentProjectId || undefined,
          },
          ev => applyEvent(turnId, ev),
          controller.signal,
        );
        // 流正常结束但没收到终止事件（防御）
        const turn = findTurn(get().entries, turnId);
        if (turn?.status === 'streaming') {
          mutateTurn(turnId, t => ({ ...t, status: 'done', blocks: freezeBlocks(t.blocks) }));
        }
      } catch (err) {
        if (controller.signal.aborted) {
          mutateTurn(turnId, t => ({ ...t, status: 'cancelled', blocks: freezeBlocks(t.blocks) }));
        } else {
          const message = err instanceof Error ? err.message : String(err);
          mutateTurn(turnId, t => ({
            ...t,
            status: 'error',
            blocks: [...freezeBlocks(t.blocks), { kind: 'error-note', id: uid(), message }],
          }));
        }
      } finally {
        set({ streaming: false, streamLabel: '', abortController: null });
        void useAppStore.getState().refreshSessions();
      }
    },

    stop: async () => {
      const { streaming, abortController } = get();
      if (!streaming) return;
      const sid = useAppStore.getState().currentSessionId;
      if (sid) {
        try {
          await cancelChat(sid);
        } catch {
          abortController?.abort();
        }
      }
      // 优先等后端 cancelled 事件自然收尾（保留最终内容与 token 统计）；15s 未收尾则兜底中断
      window.setTimeout(() => {
        const s = get();
        if (s.streaming) s.abortController?.abort();
      }, 15000);
    },

    loadHistory: async sessionId => {
      if (!sessionId) {
        set({ entries: [], contextTokens: 0 });
        return;
      }
      set({ historyLoading: true });
      try {
        const data = await getSessionMessages(sessionId);
        set({ entries: buildEntriesFromHistory(data.messages), contextTokens: data.context_tokens ?? 0 });
        useTodoStore.getState().loadFromMessages(data.messages);
      } catch (err) {
        set({ entries: [] });
        toast('error', err instanceof Error ? err.message : '加载会话消息失败');
      } finally {
        set({ historyLoading: false });
      }
    },

    clearEntries: () => set({ entries: [], contextTokens: 0 }),

    decideToolBlock: async (turnId, blockId, approved, raiseBy) => {
      const sid = useAppStore.getState().currentSessionId;
      const turn = findTurn(get().entries, turnId);
      const block = turn?.blocks.find(b => b.id === blockId);
      if (!sid || !turn || block?.kind !== 'tool' || !block.toolCallId) return;
      try {
        await decideTool(sid, block.toolCallId, approved, raiseBy);
        mutateTurn(turnId, t => ({
          ...t,
          blocks: t.blocks.map(b =>
            b.kind === 'tool' && b.id === blockId
              ? { ...b, decision: { approved, raisedBy: raiseBy } }
              : b,
          ),
        }));
      } catch (err) {
        toast('error', err instanceof Error ? err.message : '审批请求失败');
      }
    },

    decideIterationBlock: async (turnId, blockId, approved, raiseBy) => {
      const sid = useAppStore.getState().currentSessionId;
      const turn = findTurn(get().entries, turnId);
      const block = turn?.blocks.find(b => b.id === blockId);
      if (!sid || !turn || block?.kind !== 'iteration') return;
      try {
        await decideTool(sid, block.toolCallId, approved, raiseBy);
        mutateTurn(turnId, t => ({
          ...t,
          blocks: t.blocks.map(b =>
            b.kind === 'iteration' && b.id === blockId
              ? { ...b, decision: { approved, raisedBy: raiseBy } }
              : b,
          ),
        }));
      } catch (err) {
        toast('error', err instanceof Error ? err.message : '审批请求失败');
      }
    },
  };
});
