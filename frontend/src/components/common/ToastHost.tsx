import { AlertCircle, CheckCircle2, Info, X } from 'lucide-react';
import { useUiStore } from '../../stores/uiStore';
import { cn } from '../../utils/misc';

const ICONS = {
  success: <CheckCircle2 size={16} className="text-emerald-500" />,
  error: <AlertCircle size={16} className="text-red-500" />,
  info: <Info size={16} className="text-indigo-500" />,
};

export default function ToastHost() {
  const toasts = useUiStore(s => s.toasts);
  const dismiss = useUiStore(s => s.dismissToast);

  if (toasts.length === 0) return null;

  return (
    <div className="pointer-events-none fixed right-4 bottom-4 z-[70] flex flex-col gap-2">
      {toasts.map(t => (
        <div
          key={t.id}
          className={cn(
            'modal-in pointer-events-auto flex items-center gap-2 rounded-lg border px-3.5 py-2.5 text-sm shadow-md',
            t.type === 'success' && 'border-emerald-200 bg-white text-emerald-700',
            t.type === 'error' && 'border-red-200 bg-white text-red-700',
            t.type === 'info' && 'border-indigo-200 bg-white text-zinc-700',
          )}
        >
          {ICONS[t.type]}
          <span className="max-w-xs">{t.message}</span>
          <button className="icon-btn h-5 w-5" onClick={() => dismiss(t.id)} aria-label="关闭提示">
            <X size={12} />
          </button>
        </div>
      ))}
    </div>
  );
}
