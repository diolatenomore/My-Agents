import { create } from 'zustand';
import { uid } from '../utils/misc';

export type ToastType = 'success' | 'error' | 'info';

export interface Toast {
  id: string;
  type: ToastType;
  message: string;
}

export interface ConfirmOptions {
  title: string;
  message?: string;
  confirmText?: string;
  cancelText?: string;
  danger?: boolean;
}

interface ConfirmRequest extends ConfirmOptions {
  resolve: (ok: boolean) => void;
}

interface UiState {
  toasts: Toast[];
  confirmReq: ConfirmRequest | null;
  toast: (type: ToastType, message: string, durationMs?: number) => void;
  dismissToast: (id: string) => void;
  confirm: (opts: ConfirmOptions) => Promise<boolean>;
  resolveConfirm: (ok: boolean) => void;
}

export const useUiStore = create<UiState>((set, get) => ({
  toasts: [],
  confirmReq: null,
  toast: (type, message, durationMs = 3500) => {
    const id = uid();
    set(s => ({ toasts: [...s.toasts, { id, type, message }] }));
    window.setTimeout(() => get().dismissToast(id), durationMs);
  },
  dismissToast: id => set(s => ({ toasts: s.toasts.filter(t => t.id !== id) })),
  confirm: opts =>
    new Promise<boolean>(resolve => {
      set({ confirmReq: { ...opts, resolve } });
    }),
  resolveConfirm: ok => {
    const req = get().confirmReq;
    set({ confirmReq: null });
    req?.resolve(ok);
  },
}));

export const toast = (type: ToastType, message: string) =>
  useUiStore.getState().toast(type, message);

export const confirmDialog = (opts: ConfirmOptions) => useUiStore.getState().confirm(opts);
