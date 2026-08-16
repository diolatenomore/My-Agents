export default function UserBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-end py-2">
      <div className="max-w-[85%] rounded-2xl rounded-br-md bg-indigo-600 px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap break-words text-white">
        {content}
      </div>
    </div>
  );
}
