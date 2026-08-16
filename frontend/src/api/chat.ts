import type { StreamEvent } from '../types';
import { ApiError } from './client';

export interface ChatStreamBody {
  query: string;
  session_id?: string;
  model_id?: string;
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
