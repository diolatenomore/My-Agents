import { apiFetch } from './client';
import type { ProjectDTO, ProjectFormValues } from '../types';

export function listProjects(): Promise<ProjectDTO[]> {
  return apiFetch<ProjectDTO[]>('/api/projects');
}

export function createProject(values: ProjectFormValues): Promise<ProjectDTO> {
  return apiFetch('/api/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(values),
  });
}

export function updateProject(
  projectId: string,
  values: Partial<ProjectFormValues>,
): Promise<ProjectDTO> {
  return apiFetch(`/api/projects/${projectId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(values),
  });
}

export function deleteProject(projectId: string): Promise<{ code: number; message: string }> {
  return apiFetch(`/api/projects/${projectId}`, { method: 'DELETE' });
}
