import { create } from 'zustand';
import type { ModelConfig, SessionDTO } from '../types';
import { listSessions } from '../api/sessions';
import { listModels } from '../api/models';
import { toast } from './uiStore';

const SESSION_KEY = 'session_id';
const MODEL_KEY = 'selected_model_id';

interface AppState {
  sessions: SessionDTO[];
  sessionsLoading: boolean;
  models: ModelConfig[];
  modelsLoading: boolean;
  currentSessionId: string;
  selectedModelId: string;
  init: () => Promise<void>;
  refreshSessions: () => Promise<void>;
  refreshModels: () => Promise<void>;
  selectModel: (id: string) => void;
  /** 流式过程中收到 session_ready 时收编新会话（只登记，不触发历史加载） */
  adoptSession: (id: string) => void;
}

export const useAppStore = create<AppState>((set, get) => ({
  sessions: [],
  sessionsLoading: false,
  models: [],
  modelsLoading: false,
  currentSessionId: localStorage.getItem(SESSION_KEY) ?? '',
  selectedModelId: localStorage.getItem(MODEL_KEY) ?? '',

  init: async () => {
    await Promise.all([get().refreshSessions(), get().refreshModels()]);
  },

  refreshSessions: async () => {
    set({ sessionsLoading: true });
    try {
      const sessions = await listSessions();
      set({ sessions });
    } catch (err) {
      toast('error', err instanceof Error ? err.message : '加载会话列表失败');
    } finally {
      set({ sessionsLoading: false });
    }
  },

  refreshModels: async () => {
    set({ modelsLoading: true });
    try {
      const models = await listModels();
      const prev = get().selectedModelId;
      let selected = prev;
      if (models.length === 0) {
        selected = '';
      } else if (!selected || !models.some(m => m.id === selected)) {
        selected = models[0].id;
      }
      if (selected !== prev) localStorage.setItem(MODEL_KEY, selected);
      set({ models, selectedModelId: selected });
    } catch (err) {
      toast('error', err instanceof Error ? err.message : '加载模型列表失败');
    } finally {
      set({ modelsLoading: false });
    }
  },

  selectModel: id => {
    localStorage.setItem(MODEL_KEY, id);
    set({ selectedModelId: id });
  },

  adoptSession: id => {
    localStorage.setItem(SESSION_KEY, id);
    if (get().currentSessionId !== id) set({ currentSessionId: id });
    void get().refreshSessions();
  },
}));
