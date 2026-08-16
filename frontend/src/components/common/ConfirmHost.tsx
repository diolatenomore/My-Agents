import { useUiStore } from '../../stores/uiStore';
import { cn } from '../../utils/misc';

export default function ConfirmHost() {
  const req = useUiStore(s => s.confirmReq);
  const resolve = useUiStore(s => s.resolveConfirm);

  if (!req) return null;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4"
      onMouseDown={e => {
        if (e.target === e.currentTarget) resolve(false);
      }}
    >
      <div className="modal-in w-full max-w-sm rounded-xl bg-white p-5 shadow-xl">
        <h3 className="text-sm font-semibold text-zinc-900">{req.title}</h3>
        {req.message && <p className="mt-2 text-sm leading-relaxed text-zinc-500">{req.message}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <button className="btn btn-outline" onClick={() => resolve(false)}>
            {req.cancelText ?? '取消'}
          </button>
          <button
            className={cn('btn', req.danger ? 'btn-danger' : 'btn-primary')}
            onClick={() => resolve(true)}
          >
            {req.confirmText ?? '确认'}
          </button>
        </div>
      </div>
    </div>
  );
}
