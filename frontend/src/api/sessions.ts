import { apiFetch } from './client';
import type { SessionDTO, SessionMessagesResponse } from '../types';

export function listSessions(): Promise<SessionDTO[]> {
  return apiFetch<SessionDTO[]>('/api/sessions');
}

export function deleteSession(sessionId: string): Promise<{ code: number; message: string }> {
  return apiFetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
}

/** 注意：title 走 query 参数（后端约定），≤50 字 */
export function renameSession(
  sessionId: string,
  title: string,
): Promise<{ code: number; message: string }> {
  return apiFetch(`/api/sessions/${sessionId}/title?title=${encodeURIComponent(title)}`, {
    method: 'PUT',
  });
}

export function getSessionMessages(sessionId: string): Promise<SessionMessagesResponse> {
  return apiFetch(`/api/sessions/${sessionId}/messages`);
}
