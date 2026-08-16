import ChatHeader from './ChatHeader';
import MessageList from './MessageList';
import ChatInput from './ChatInput';
import ReviewDrawer from '../review/ReviewDrawer';

export default function ChatPage() {
  return (
    <div className="flex h-full min-h-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        <ChatHeader />
        <MessageList />
        <ChatInput />
      </div>
      <ReviewDrawer />
    </div>
  );
}
