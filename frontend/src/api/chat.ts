import type { SkillSegment, StreamEvent } from '../types';
import { ApiError } from './client';

export interface ChatStreamBody {
  query: string;
  session_id?: string;
  model_id?: string;
  /** 仅新会话首条消息时生效（会话归属项目后不再变化） */
  project_id?: string;
  /** "/" 选择的显式注入技能名（后端前置注入到模型版 user message） */
  skills?: string[];
  /** 带 skill 占位符时的展示分段（仅持久化展示用，不进模型路径） */
  segments?: SkillSegment[];
}

/**
 * 消费 POST /api/chat/stream 的 SSE 流。
 * 后端在参数缺失（401/402）时会返回普通 JSON 而非 SSE，此时抛 ApiError。
 */
export async function streamChat(
  body: ChatStreamBody,
  onEvent: (ev: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });

  const contentType = res.headers.get('content-type') ?? '';
  if (!contentType.includes('text/event-stream')) {
    let data: { message?: string } | null = null;
    try {
      data = (await res.json()) as { message?: string };
    } catch {
      // 非 JSON 响应体，走通用错误信息
    }
    throw new ApiError(data?.message ?? `请求失败（HTTP ${res.status}）`, res.status, data);
  }
  if (!res.body) {
    throw new ApiError('响应流为空', res.status);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split('\n\n');
    buffer = blocks.pop() ?? '';
    for (const block of blocks) {
      let dataStr = '';
      for (const line of block.split('\n')) {
        if (line.startsWith('data: ')) dataStr = line.slice(6);
      }
      if (!dataStr) continue;
      let parsed: StreamEvent;
      try {
        parsed = JSON.parse(dataStr) as StreamEvent;
      } catch {
        continue;
      }
      onEvent(parsed);
    }
  }
}

export function cancelChat(sessionId: string): Promise<Response> {
  return fetch(`/api/chat/cancel/${sessionId}`, { method: 'POST' });
}
