import { create } from 'zustand';
import type { ModelConfig, ProjectDTO, SessionDTO } from '../types';
import { listSessions } from '../api/sessions';
import { listModels } from '../api/models';
import { listProjects } from '../api/projects';
import { toast } from './uiStore';

const SESSION_KEY = 'session_id';
const MODEL_KEY = 'selected_model_id';
const PROJECT_KEY = 'project_id';

interface AppState {
  sessions: SessionDTO[];
  sessionsLoading: boolean;
  models: ModelConfig[];
  modelsLoading: boolean;
  projects: ProjectDTO[];
  projectsLoading: boolean;
  currentSessionId: string;
  /** 当前选中的项目（'' = 无项目/普通聊天），新会话将归属该项目 */
  currentProjectId: string;
  selectedModelId: string;
  init: () => Promise<void>;
  refreshSessions: () => Promise<void>;
  refreshModels: () => Promise<void>;
  refreshProjects: () => Promise<void>;
  selectModel: (id: string) => void;
  /** 流式过程中收到 session_ready 时收编新会话（只登记，不触发历史加载） */
  adoptSession: (id: string) => void;
}

export const useAppStore = create<AppState>((set, get) => ({
  sessions: [],
  sessionsLoading: false,
  models: [],
  modelsLoading: false,
  projects: [],
  projectsLoading: false,
  currentSessionId: localStorage.getItem(SESSION_KEY) ?? '',
  currentProjectId: localStorage.getItem(PROJECT_KEY) ?? '',
  selectedModelId: localStorage.getItem(MODEL_KEY) ?? '',

  init: async () => {
    await Promise.all([get().refreshSessions(), get().refreshModels(), get().refreshProjects()]);
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

  refreshProjects: async () => {
    set({ projectsLoading: true });
    try {
      const projects = await listProjects();
      set({ projects });
      // 已删除的项目被选中时回退到「无项目」
      const current = get().currentProjectId;
      if (current && !projects.some(p => p.project_id === current)) {
        localStorage.setItem(PROJECT_KEY, '');
        set({ currentProjectId: '' });
      }
    } catch (err) {
      toast('error', err instanceof Error ? err.message : '加载项目列表失败');
    } finally {
      set({ projectsLoading: false });
    }
  },

  adoptSession: id => {
    localStorage.setItem(SESSION_KEY, id);
    if (get().currentSessionId !== id) set({ currentSessionId: id });
    void get().refreshSessions();
  },
}));
