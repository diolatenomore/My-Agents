import { apiFetch } from './client';
import type { ReviewTree, ReviewContent } from '../types';

export function getReviewTree(
  taskId: string,
): Promise<{ code: number; message: string; review_tree: ReviewTree | null }> {
  return apiFetch(`/api/vfs/review/${taskId}`);
}

export function reviewAll(
  taskId: string,
  approved: boolean,
): Promise<{ code: number; message: string }> {
  return apiFetch(`/api/vfs/review/${taskId}?approved=${approved}`, { method: 'POST' });
}

export function reviewItem(
  taskId: string,
  itemId: string,
  approved: boolean,
): Promise<{ code: number; message: string }> {
  return apiFetch(`/api/vfs/review/${taskId}/item/${itemId}?approved=${approved}`, {
    method: 'POST',
  });
}

export function getReviewItemContent(
  taskId: string,
  itemId: string,
): Promise<{ code: number; message: string; content: ReviewContent | null }> {
  return apiFetch(`/api/vfs/review/${taskId}/item/${itemId}/content`);
}
