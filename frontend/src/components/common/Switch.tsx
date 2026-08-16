import { cn } from '../../utils/misc';

interface SwitchProps {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}

export default function Switch({ checked, onChange, disabled }: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      className={cn(
        'relative h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors',
        checked ? 'bg-indigo-600' : 'bg-zinc-300',
        disabled && 'cursor-not-allowed opacity-50',
      )}
      onClick={() => onChange(!checked)}
    >
      <span
        className={cn(
          'absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all',
          checked ? 'left-[18px]' : 'left-0.5',
        )}
      />
    </button>
  );
}
