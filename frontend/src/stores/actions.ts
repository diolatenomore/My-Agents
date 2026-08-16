import { useAppStore } from './appStore';
import { useChatStore } from './chatStore';
import { useReviewStore } from './reviewStore';
import { useTodoStore } from './todoStore';
import { deleteSession, renameSession } from '../api/sessions';
import { confirmDialog, toast } from './uiStore';

/** 应用启动：加载会话与模型，若有记忆中的会话则恢复历史与审批树 */
export async function initApp() {
  const app = useAppStore.getState();
  await app.init();
  const sid = useAppStore.getState().currentSessionId;
  if (sid) {
    await Promise.all([
      useChatStore.getState().loadHistory(sid),
      useReviewStore.getState().load(sid),
    ]);
  }
}

/** 切换会话（流式过程中禁止） */
export async function switchSession(sessionId: string) {
  const chat = useChatStore.getState();
  if (chat.streaming) {
    toast('info', '正在回复中，请等待完成或先停止');
    return;
  }
  if (useAppStore.getState().currentSessionId === sessionId) return;
  localStorage.setItem('session_id', sessionId);
  useAppStore.setState({ currentSessionId: sessionId });
  useReviewStore.getState().clear();
  useTodoStore.getState().clear();
  await Promise.all([
    useChatStore.getState().loadHistory(sessionId),
    useReviewStore.getState().load(sessionId),
  ]);
}

/** 新建会话：清空当前会话状态（首个消息发送时后端才真正创建） */
export function newSession() {
  const chat = useChatStore.getState();
  if (chat.streaming) {
    toast('info', '正在回复中，请等待完成或先停止');
    return;
  }
  localStorage.removeItem('session_id');
  useAppStore.setState({ currentSessionId: '' });
  useChatStore.getState().clearEntries();
  useReviewStore.getState().clear();
  useReviewStore.setState({ open: false });
  useTodoStore.getState().clear();
}

/** 删除会话（带确认），删除当前会话则回到新会话状态 */
export async function removeSession(sessionId: string) {
  const ok = await confirmDialog({
    title: '删除会话',
    message: '确定删除该会话？删除后不可恢复。',
    confirmText: '删除',
    danger: true,
  });
  if (!ok) return;
  try {
    await deleteSession(sessionId);
    if (useAppStore.getState().currentSessionId === sessionId) {
      newSession();
    }
    await useAppStore.getState().refreshSessions();
    toast('success', '会话已删除');
  } catch (err) {
    toast('error', err instanceof Error ? err.message : '删除失败');
  }
}

/** 会话重命名（title ≤ 50 字，走 query 参数） */
export async function renameSessionAction(sessionId: string, title: string): Promise<boolean> {
  try {
    const res = await renameSession(sessionId, title);
    if (res.code === 200) {
      await useAppStore.getState().refreshSessions();
      return true;
    }
    toast('error', res.message || '重命名失败');
    return false;
  } catch (err) {
    toast('error', err instanceof Error ? err.message : '重命名失败');
    return false;
  }
}
