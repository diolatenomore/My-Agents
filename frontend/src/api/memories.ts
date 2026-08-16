import { apiFetch } from './client';
import type { MemoryListResponse } from '../types';

export function listMemories(params: {
  limit: number;
  offset: number;
  memoryType?: string;
}): Promise<MemoryListResponse> {
  const q = new URLSearchParams();
  q.set('limit', String(params.limit));
  q.set('offset', String(params.offset));
  if (params.memoryType) q.set('memory_type', params.memoryType);
  return apiFetch(`/api/memories?${q.toString()}`);
}

export function updateMemory(
  memoryId: string,
  body: { value: string; key: string },
): Promise<{ code: number; message: string }> {
  return apiFetch(`/api/memories/${memoryId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export function deleteMemory(memoryId: string): Promise<{ code: number; message: string }> {
  return apiFetch(`/api/memories/${memoryId}`, { method: 'DELETE' });
}
