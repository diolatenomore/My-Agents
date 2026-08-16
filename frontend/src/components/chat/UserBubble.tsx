import type { SkillSegment } from '../../types';

export default function UserBubble({ content, segments }: { content: string; segments?: SkillSegment[] }) {
  return (
    <div className="flex justify-end py-2">
      <div className="max-w-[85%] rounded-2xl rounded-br-md bg-indigo-600 px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap break-words text-white">
        {segments?.length
          ? segments.map((seg, i) =>
              seg.type === 'skill' ? (
                <span
                  key={i}
                  className="mx-0.5 inline-flex items-center gap-1 rounded-full bg-white/20 px-2 py-0.5 align-middle text-xs font-medium"
                >
                  ✦ {seg.name}
                </span>
              ) : (
                seg.text
              ),
            )
          : content}
      </div>
    </div>
  );
}
