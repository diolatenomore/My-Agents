import { create } from 'zustand';
import type { StoredMessage, TodoItem, TodoStatus } from '../types';

/**
 * Todo 状态：todo 工具无独立 HTTP 接口，
 * 数据来源于 SSE tool_result（name === 'todo'）与会话历史消息（与后端 _hydrate_todo_store 同源逻辑）。
 */
interface TodoState {
  todos: TodoItem[];
  summary: string;
  /** SSE tool_result(name=todo) 到达时实时更新 */
  ingestResult: (result: string) => void;
  /** 切换会话时从历史消息恢复最近一次 todo 状态 */
  loadFromMessages: (messages: StoredMessage[]) => void;
  clear: () => void;
}

function parseTodo(content: string): { todos: TodoItem[]; summary: string } | null {
  try {
    const payload = JSON.parse(content) as {
      todos?: Array<{ id?: string | number; text?: string; content?: string; status?: string }>;
      summary?: unknown;
    };
    if (!Array.isArray(payload.todos)) return null;
    const todos: TodoItem[] = payload.todos
      .filter(t => t != null && typeof t === 'object' && typeof (t.text ?? t.content) === 'string')
      .map((t, i) => ({
        id: t.id ?? i,
        text: (t.text ?? t.content) as string,
        status: normalizeStatus(t.status),
      }));
    return { todos, summary: typeof payload.summary === 'string' ? payload.summary : '' };
  } catch {
    return null;
  }
}

function normalizeStatus(s: string | undefined): TodoStatus {
  if (s === 'in_progress' || s === 'completed' || s === 'cancelled') return s;
  return 'pending';
}

export const useTodoStore = create<TodoState>(set => ({
  todos: [],
  summary: '',

  ingestResult: result => {
    const parsed = parseTodo(result);
    if (parsed) set({ todos: parsed.todos, summary: parsed.summary });
  },

  loadFromMessages: messages => {
    // tool_call_id → 工具名映射（用于识别 todo 工具的返回）
    const nameByCallId = new Map<string, string>();
    for (const m of messages) {
      if (m.role === 'assistant' && m.tool_calls) {
        for (const tc of m.tool_calls) nameByCallId.set(tc.id, tc.name);
      }
    }
    const recent = messages.slice(-10);
    for (let i = recent.length - 1; i >= 0; i--) {
      const m = recent[i];
      if (m.role !== 'tool' || !m.tool_call_id) continue;
      if (nameByCallId.get(m.tool_call_id) !== 'todo') continue;
      if (typeof m.content !== 'string') continue;
      const parsed = parseTodo(m.content);
      if (parsed) {
        set({ todos: parsed.todos, summary: parsed.summary });
        return;
      }
    }
    set({ todos: [], summary: '' });
  },

  clear: () => set({ todos: [], summary: '' }),
}));
