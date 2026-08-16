import type { LucideIcon } from 'lucide-react';

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description?: string;
}

export default function EmptyState({ icon: Icon, title, description }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-14 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-zinc-100 text-zinc-400">
        <Icon size={22} />
      </div>
      <div className="mt-3 text-sm font-medium text-zinc-500">{title}</div>
      {description && <div className="mt-1 text-xs text-zinc-400">{description}</div>}
    </div>
  );
}
