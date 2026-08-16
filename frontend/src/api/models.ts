import { apiFetch } from './client';
import type { ModelConfig, ModelFormValues } from '../types';

export function listModels(): Promise<ModelConfig[]> {
  return apiFetch<ModelConfig[]>('/api/models');
}

export function createModel(
  body: ModelFormValues,
): Promise<{ code: number; message: string; data: ModelConfig }> {
  return apiFetch('/api/models', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/** 编辑时 api_key 留空则后端保持原 Key 不变 */
export function updateModel(
  modelId: string,
  body: ModelFormValues,
): Promise<{ code: number; message: string; data: ModelConfig }> {
  return apiFetch(`/api/models/${modelId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export function deleteModel(modelId: string): Promise<{ code: number; message: string }> {
  return apiFetch(`/api/models/${modelId}`, { method: 'DELETE' });
}
