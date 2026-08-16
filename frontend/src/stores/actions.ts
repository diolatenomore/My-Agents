import { useAppStore } from './appStore';
import { useChatStore } from './chatStore';
import { useReviewStore } from './reviewStore';
import { useTodoStore } from './todoStore';
import { deleteSession, renameSession } from '../api/sessions';
import { deleteProject, updateProject } from '../api/projects';
import { confirmDialog, toast } from './uiStore';
import type { ProjectDTO } from '../types';

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

/** 新建会话并指定归属项目（'' = 普通聊天）：设置归属后清空当前会话状态，首个消息发送时后端才真正创建 */
export function newSessionInProject(projectId: string) {
  if (useChatStore.getState().streaming) {
    toast('info', '正在回复中，请等待完成或先停止');
    return;
  }
  localStorage.setItem('project_id', projectId);
  useAppStore.setState({ currentProjectId: projectId });
  newSession();
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

/** 项目重命名（仅修改名称，后端校验重名） */
export async function renameProjectAction(projectId: string, name: string): Promise<boolean> {
  try {
    await updateProject(projectId, { name });
    await useAppStore.getState().refreshProjects();
    return true;
  } catch (err) {
    toast('error', err instanceof Error ? err.message : '重命名失败');
    return false;
  }
}

/** 删除项目（带确认）：级联删除其归属会话及相关数据；当前会话被删时回到新会话状态 */
export async function removeProjectAction(project: ProjectDTO) {
  const sessionText = project.session_count > 0 ? `其 ${project.session_count} 个会话及相关数据将被一并删除，` : '';
  const ok = await confirmDialog({
    title: '删除项目',
    message: `确定删除项目「${project.name}」？${sessionText}删除后不可恢复。`,
    confirmText: '删除',
    danger: true,
  });
  if (!ok) return;
  try {
    const app = useAppStore.getState();
    const currentDeleted = app.sessions.some(
      s => s.project_id === project.project_id && s.session_id === app.currentSessionId,
    );
    await deleteProject(project.project_id);
    if (currentDeleted) newSession();
    await Promise.all([
      useAppStore.getState().refreshProjects(),
      useAppStore.getState().refreshSessions(),
    ]);
    toast('success', '项目已删除');
  } catch (err) {
    toast('error', err instanceof Error ? err.message : '删除失败');
  }
}
