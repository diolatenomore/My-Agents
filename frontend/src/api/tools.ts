import { apiFetch } from './client';

/**
 * 工具审批决策。
 * threshold_tool_call / threshold_iteration 的 tool_call_id 以 `__iter__` 开头表示迭代上限审批。
 * raise_limit_by 仅 approved=true 时有效，ge=1。
 */
export function decideTool(
  sessionId: string,
  toolCallId: string,
  approved: boolean,
  raiseLimitBy?: number,
): Promise<{ code: number; message: string; new_threshold_raise?: number }> {
  let url = `/api/tools/decide/${sessionId}/${toolCallId}?approved=${approved}`;
  if (approved && raiseLimitBy != null && raiseLimitBy >= 1) {
    url += `&raise_limit_by=${raiseLimitBy}`;
  }
  return apiFetch(url, { method: 'POST' });
}
