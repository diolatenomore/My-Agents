import { useEffect, useState } from 'react';
import { FolderOpen, Pencil, Plus, Trash2 } from 'lucide-react';
import Modal from '../common/Modal';
import { useAppStore } from '../../stores/appStore';
import { createProject, deleteProject, updateProject } from '../../api/projects';
import { confirmDialog, toast } from '../../stores/uiStore';
import type { ProjectDTO } from '../../types';

type Mode = 'list' | 'create' | 'edit';

/** 项目管理对话框：列表 + 新建/编辑/删除。工作目录为手动输入的绝对路径（后端校验存在）。initialMode='create' 时直达新建表单，创建成功即关闭 */
export default function ProjectManagerDialog({
  open,
  onClose,
  initialMode = 'list',
}: {
  open: boolean;
  onClose: () => void;
  initialMode?: Mode;
}) {
  const projects = useAppStore(s => s.projects);
  const refreshProjects = useAppStore(s => s.refreshProjects);
  const refreshSessions = useAppStore(s => s.refreshSessions);

  const [mode, setMode] = useState<Mode>('list');
  const [editing, setEditing] = useState<ProjectDTO | null>(null);
  const [name, setName] = useState('');
  const [workDir, setWorkDir] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      setMode(initialMode);
      setEditing(null);
      setError('');
    }
  }, [open, initialMode]);

  const openForm = (project: ProjectDTO | null) => {
    setEditing(project);
    setName(project?.name ?? '');
    setWorkDir(project?.work_dir ?? '');
    setError('');
    setMode(project ? 'edit' : 'create');
  };

  const submit = async () => {
    if (submitting) return;
    if (!name.trim()) {
      setError('请输入项目名称');
      return;
    }
    if (!workDir.trim()) {
      setError('请输入工作目录的绝对路径');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      if (mode === 'create') {
        await createProject({ name: name.trim(), work_dir: workDir.trim() });
        toast('success', '项目已创建');
      } else if (editing) {
        await updateProject(editing.project_id, { name: name.trim(), work_dir: workDir.trim() });
        toast('success', '项目已更新');
      }
      await Promise.all([refreshProjects(), refreshSessions()]);
      // 从侧边栏 + 号直达新建时，创建成功即关闭
      if (mode === 'create' && initialMode === 'create') {
        onClose();
        return;
      }
      setMode('list');
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (project: ProjectDTO) => {
    const ok = await confirmDialog({
      title: '删除项目',
      message: `确定删除项目「${project.name}」？其会话将保留，并回到「无项目」状态。`,
      confirmText: '删除',
      danger: true,
    });
    if (!ok) return;
    try {
      await deleteProject(project.project_id);
      await Promise.all([refreshProjects(), refreshSessions()]);
      toast('success', '项目已删除');
    } catch (err) {
      toast('error', err instanceof Error ? err.message : '删除失败');
    }
  };

  return (
    <Modal
      open={open}
      title={mode === 'list' ? '项目管理' : mode === 'create' ? '新建项目' : '编辑项目'}
      onClose={onClose}
      width="max-w-lg"
      footer={
        mode === 'list' ? (
          <>
            <button className="btn btn-outline" onClick={onClose}>
              关闭
            </button>
            <button className="btn btn-primary" onClick={() => openForm(null)}>
              <Plus size={14} />
              新建项目
            </button>
          </>
        ) : (
          <>
            <button
              className="btn btn-outline"
              onClick={() => (initialMode === 'create' ? onClose() : setMode('list'))}
            >
              {initialMode === 'create' ? '取消' : '返回'}
            </button>
            <button className="btn btn-primary" disabled={submitting} onClick={() => void submit()}>
              {submitting ? '保存中…' : '保存'}
            </button>
          </>
        )
      }
    >
      {mode === 'list' ? (
        projects.length === 0 ? (
          <div className="py-8 text-center text-xs text-zinc-400">
            暂无项目。新建项目后，归属它的会话将以项目目录为工作目录。
          </div>
        ) : (
          <div className="space-y-2">
            {projects.map(p => (
              <div key={p.project_id} className="group flex items-center gap-3 rounded-lg border border-zinc-100 px-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <FolderOpen size={14} className="shrink-0 text-indigo-500" />
                    <span className="truncate text-[13px] font-medium text-zinc-800">{p.name}</span>
                    <span className="shrink-0 text-[11px] text-zinc-400">{p.session_count} 会话</span>
                  </div>
                  <div className="mt-0.5 truncate text-[11px] text-zinc-400" title={p.work_dir}>
                    {p.work_dir}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <button className="icon-btn h-7 w-7" title="编辑" onClick={() => openForm(p)}>
                    <Pencil size={13} />
                  </button>
                  <button
                    className="icon-btn h-7 w-7 hover:text-red-500"
                    title="删除"
                    onClick={() => void handleDelete(p)}
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )
      ) : (
        <div className="space-y-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-zinc-600">项目名称</label>
            <input
              className="input"
              maxLength={50}
              placeholder="如 my-agents"
              value={name}
              autoFocus
              onChange={e => setName(e.target.value)}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-zinc-600">
              工作目录（已存在目录的绝对路径）
            </label>
            <input
              className="input font-mono text-xs"
              placeholder="如 D:\PythonCode\my-project"
              value={workDir}
              onChange={e => setWorkDir(e.target.value)}
            />
            <p className="mt-1 text-[11px] text-zinc-400">
              归属该项目的会话中，文件操作与命令的相对路径将以该目录为基准解析。
            </p>
          </div>
          {error && <div className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-600">{error}</div>}
        </div>
      )}
    </Modal>
  );
}
