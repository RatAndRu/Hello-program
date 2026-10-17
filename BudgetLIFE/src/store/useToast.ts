import { create } from 'zustand';
import { uid } from '../lib/id';

export interface Toast {
  id: string;
  title: string;
  description?: string;
  kind: 'success' | 'error' | 'info' | 'warning';
  duration?: number;
}

interface ToastStore {
  toasts: Toast[];
  push: (t: Omit<Toast, 'id'>) => string;
  dismiss: (id: string) => void;
}

export const useToastStore = create<ToastStore>((set, get) => ({
  toasts: [],
  push: (t) => {
    const id = uid('toast');
    set((s) => ({ toasts: [...s.toasts, { ...t, id }] }));
    const duration = t.duration ?? (t.kind === 'error' ? 7000 : 4200);
    setTimeout(() => get().dismiss(id), duration);
    return id;
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));

export const toast = {
  success: (title: string, description?: string) => useToastStore.getState().push({ title, description, kind: 'success' }),
  error: (title: string, description?: string) => useToastStore.getState().push({ title, description, kind: 'error' }),
  info: (title: string, description?: string) => useToastStore.getState().push({ title, description, kind: 'info' }),
  warning: (title: string, description?: string) => useToastStore.getState().push({ title, description, kind: 'warning' }),
};
