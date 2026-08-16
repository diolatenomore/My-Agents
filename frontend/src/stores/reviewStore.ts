import { create } from 'zustand';
import type { ReviewTree } from '../types';
import { getReviewTree, reviewAll, reviewItem } from '../api/review';
import { toast } from './uiStore';
import { useAppStore } from './appStore';

export type DrawerTab = 'review' | 'todo';

interface ReviewState {
  tree: ReviewTree | null;
  loading: boolean;
  open: boolean;
  tab: DrawerTab;
  setOpen: (open: boolean) => void;
  setTab: (tab: DrawerTab) => void;
  /** 会话切换 / done 事件后拉取审批树；有待审批项时自动打开抽屉 */
  load: (taskId: string) => Promise<void>;
  /** SSE done/cancelled 事件直接附带审批树时 */
  present: (tree: ReviewTree) => void;
  clear: () => void;
  decideAll: (approved: boolean) => Promise<void>;
  decideItem: (itemId: string, approved: boolean) => Promise<void>;
}

export const useReviewStore = create<ReviewState>((set, get) => ({
  tree: null,
  loading: false,
  open: false,
  tab: 'review',

  setOpen: open => set({ open }),
  setTab: tab => set({ tab }),

  load: async taskId => {
    if (!taskId) return;
    set({ loading: true });
    try {
      const data = await getReviewTree(taskId);
      if (data.code === 200 && data.review_tree && data.review_tree.items?.length) {
        set({ tree: data.review_tree, open: true, tab: 'review' });
      } else {
        set({ tree: null });
      }
    } catch {
      // 无审批项时后端可能返回异常，静默处理
    } finally {
      set({ loading: false });
    }
  },

  present: tree => {
    if (tree.items?.length) set({ tree, open: true, tab: 'review' });
  },

  clear: () => set({ tree: null }),

  decideAll: async approved => {
    const tree = get().tree;
    const taskId = tree?.task_id || useAppStore.getState().currentSessionId;
    if (!tree || !taskId) return;
    try {
      const res = await reviewAll(taskId, approved);
      if (res.code === 200) {
        toast('success', approved ? '已通过全部变更' : '已拒绝全部变更');
        await get().load(taskId);
      } else {
        toast('error', res.message || '操作失败');
      }
    } catch (err) {
      toast('error', err instanceof Error ? err.message : '网络错误');
    }
  },

  decideItem: async (itemId, approved) => {
    const tree = get().tree;
    const taskId = tree?.task_id || useAppStore.getState().currentSessionId;
    if (!tree || !taskId) return;
    try {
      const res = await reviewItem(taskId, itemId, approved);
      if (res.code === 200) {
        await get().load(taskId);
      } else {
        toast('error', res.message || '操作失败');
      }
    } catch (err) {
      toast('error', err instanceof Error ? err.message : '网络错误');
    }
  },
}));
