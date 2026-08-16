import { apiFetch } from './client';
import type { SkillInfo } from '../types';

export function listSkills(): Promise<{ code: number; skills: SkillInfo[] }> {
  return apiFetch('/api/skills');
}

export function toggleSkill(
  name: string,
  disabled: boolean,
): Promise<{ code: number; disabled: boolean; message: string }> {
  return apiFetch(
    `/api/skills/toggle?name=${encodeURIComponent(name)}&disabled=${disabled}`,
    { method: 'PUT' },
  );
}

export function uploadSkill(
  file: File,
): Promise<{ code: number; message: string; skill?: { name: string; description: string; version: string } }> {
  const formData = new FormData();
  formData.append('file', file);
  return apiFetch('/api/skills/upload', { method: 'POST', body: formData });
}
