import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { ChevronDown, Cpu, Eye, EyeOff, Pencil, Plus, RefreshCw, Trash2 } from 'lucide-react';
import type { ModelConfig, ModelFormValues } from '../../types';
import { createModel, deleteModel, updateModel } from '../../api/models';
import { useAppStore } from '../../stores/appStore';
import { confirmDialog, toast } from '../../stores/uiStore';
import { cn } from '../../utils/misc';
import PageHeader from '../common/PageHeader';
import EmptyState from '../common/EmptyState';
import Modal from '../common/Modal';

const DEFAULT_FORM: ModelFormValues = {
  name: '',
  base_url: '',
  model: '',
  api_key: '',
  max_context_tokens: 200000,
  max_output_tokens: 64000,
  max_tool_calls: 50,
  temperature: 0.7,
  max_iterations: 30,
  think: true,
  reasoning_effort: '',
  approval_timeout: 120,
  approval_timeout_auto_approve: false,
};

function toForm(m: ModelConfig): ModelFormValues {
  return {
    name: m.name,
    base_url: m.base_url,
    model: m.model,
    api_key: '',
    max_context_tokens: m.max_context_tokens ?? 200000,
    max_output_tokens: m.max_output_tokens ?? 64000,
    max_tool_calls: m.max_tool_calls ?? 50,
    temperature: m.temperature ?? 0.7,
    max_iterations: m.max_iterations ?? 30,
    think: m.think === 1,
    reasoning_effort: m.reasoning_effort ?? '',
    approval_timeout: m.approval_timeout ?? 120,
    approval_timeout_auto_approve: m.approval_timeout_auto_approve ?? false,
  };
}

export default function ModelsPage() {
  const models = useAppStore(s => s.models);
  const refreshModels = useAppStore(s => s.refreshModels);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<ModelConfig | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState<ModelFormValues>(DEFAULT_FORM);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showKey, setShowKey] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      await refreshModels();
    } finally {
      setLoading(false);
    }
  }, [refreshModels]);

  useEffect(() => {
    void load();
  }, [load]);

  const openCreate = () => {
    setEditing(null);
    setForm(DEFAULT_FORM);
    setShowAdvanced(false);
    setShowKey(false);
    setFormOpen(true);
  };

  const openEdit = (m: ModelConfig) => {
    setEditing(m);
    setForm(toForm(m));
    setShowAdvanced(false);
    setShowKey(false);
    setFormOpen(true);
  };

  const set = <K extends keyof ModelFormValues>(key: K, value: ModelFormValues[K]) => {
    setForm(f => ({ ...f, [key]: value }));
  };

  const save = async () => {
    if (saving) return;
    if (!form.name.trim() || !form.base_url.trim() || !form.model.trim()) {
      toast('error', '名称、Base URL、模型名不能为空');
      return;
    }
    if (!editing && !form.api_key.trim()) {
      toast('error', '新建模型必须填写 API Key');
      return;
    }
    setSaving(true);
    try {
      const body: ModelFormValues = { ...form, api_key: form.api_key.trim() };
      const res = editing
        ? await updateModel(editing.id, body)
        : await createModel(body);
      if (res.code === 200) {
        toast('success', editing ? '模型已更新' : '模型已创建');
        setFormOpen(false);
        await load();
      } else {
        toast('error', res.message || '保存失败');
      }
    } catch (err) {
      toast('error', err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (m: ModelConfig) => {
    const ok = await confirmDialog({
      title: '删除模型',
      message: `确定删除模型「${m.name}」？删除后不可恢复。`,
      confirmText: '删除',
      danger: true,
    });
    if (!ok) return;
    try {
      const res = await deleteModel(m.id);
      if (res.code === 200) {
        toast('success', '模型已删除');
        await load();
      } else {
        toast('error', res.message || '删除失败');
      }
    } catch (err) {
      toast('error', err instanceof Error ? err.message : '删除失败');
    }
  };

  return (
    <div className="nice-scroll min-h-0 flex-1 overflow-y-auto bg-zinc-50">
      <div className="mx-auto w-full max-w-4xl px-6 py-6">
        <PageHeader
          icon={Cpu}
          title="模型管理"
          subtitle={models.length > 0 ? `共 ${models.length} 个模型配置` : '配置 OpenAI 兼容的模型接口'}
          actions={
            <>
              <button className="btn btn-primary" onClick={openCreate}>
                <Plus size={14} />
                新建模型
              </button>
              <button className="btn btn-outline" onClick={() => void load()} title="刷新">
                <RefreshCw size={14} className={cn(loading && 'animate-spin')} />
                刷新
              </button>
            </>
          }
        />

        <div className="space-y-2">
          {models.length === 0 ? (
            <EmptyState
              icon={Cpu}
              title={loading ? '加载中…' : '暂无模型配置'}
              description={loading ? undefined : '新建一个模型配置后即可开始对话'}
            />
          ) : (
            models.map(m => (
              <div key={m.id} className="card flex items-start gap-3 px-4 py-3.5">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-zinc-800">{m.name}</span>
                    {m.is_active === 1 && (
                      <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-600">
                        默认
                      </span>
                    )}
                  </div>
                  <div className="mt-1 font-mono text-xs break-all text-zinc-500">
                    {m.model} · {m.base_url}
                  </div>
                  <div className="mt-1 text-[11px] text-zinc-400">
                    温度 {m.temperature ?? 0.7} · 迭代上限 {m.max_iterations ?? 30} · 思考
                    {m.think === 1 ? '开' : '关'}
                    {m.reasoning_effort ? ` · 推理 ${m.reasoning_effort}` : ''} · 上下文{' '}
                    {(m.max_context_tokens ?? 200000).toLocaleString()}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <button className="icon-btn" title="编辑" onClick={() => openEdit(m)}>
                    <Pencil size={13} />
                  </button>
                  <button
                    className="icon-btn hover:text-red-500"
                    title="删除"
                    onClick={() => void handleDelete(m)}
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* 模型表单 */}
      <Modal
        open={formOpen}
        title={editing ? `编辑模型：${editing.name}` : '新建模型'}
        onClose={() => setFormOpen(false)}
        width="max-w-2xl"
        footer={
          <>
            <button className="btn btn-outline" onClick={() => setFormOpen(false)}>
              取消
            </button>
            <button className="btn btn-primary" disabled={saving} onClick={() => void save()}>
              {saving ? '保存中…' : '保存'}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <Field label="名称" required>
              <input
                className="input"
                value={form.name}
                onChange={e => set('name', e.target.value)}
                placeholder="如 DeepSeek"
              />
            </Field>
            <Field label="模型名" required>
              <input
                className="input font-mono"
                value={form.model}
                onChange={e => set('model', e.target.value)}
                placeholder="如 deepseek-chat"
              />
            </Field>
          </div>
          <Field label="Base URL" required>
            <input
              className="input font-mono"
              value={form.base_url}
              onChange={e => set('base_url', e.target.value)}
              placeholder="https://api.deepseek.com/v1"
            />
          </Field>
          <Field label="API Key" required={!editing}>
            <div className="relative">
              <input
                type={showKey ? 'text' : 'password'}
                className="input pr-14 font-mono"
                value={form.api_key}
                onChange={e => set('api_key', e.target.value)}
                placeholder={editing ? '留空则保持原有 Key 不变' : 'sk-…'}
              />
              <button
                type="button"
                className="absolute top-1/2 right-2 flex h-6 w-7 -translate-y-1/2 items-center justify-center rounded text-zinc-400 hover:text-zinc-600"
                onClick={() => setShowKey(!showKey)}
              >
                {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
          </Field>

          {/* 高级配置 */}
          <div className="rounded-lg border border-zinc-200">
            <button
              type="button"
              className="flex w-full cursor-pointer items-center gap-1.5 px-3 py-2.5 text-[13px] font-medium text-zinc-600"
              onClick={() => setShowAdvanced(!showAdvanced)}
            >
              <ChevronDown
                size={14}
                className={cn('text-zinc-400 transition-transform', !showAdvanced && '-rotate-90')}
              />
              高级配置
            </button>
            {showAdvanced && (
              <div className="grid grid-cols-2 gap-3 border-t border-zinc-100 px-3 pt-3 pb-1">
                <Field label="上下文 Token 上限">
                  <input
                    type="number"
                    className="input"
                    value={form.max_context_tokens}
                    onChange={e => set('max_context_tokens', Number(e.target.value) || 0)}
                  />
                </Field>
                <Field label="最大输出 Token">
                  <input
                    type="number"
                    className="input"
                    value={form.max_output_tokens}
                    onChange={e => set('max_output_tokens', Number(e.target.value) || 0)}
                  />
                </Field>
                <Field label="最大工具调用次数">
                  <input
                    type="number"
                    className="input"
                    value={form.max_tool_calls}
                    onChange={e => set('max_tool_calls', Number(e.target.value) || 0)}
                  />
                </Field>
                <Field label="最大迭代次数">
                  <input
                    type="number"
                    className="input"
                    value={form.max_iterations}
                    onChange={e => set('max_iterations', Number(e.target.value) || 0)}
                  />
                </Field>
                <Field label="Temperature">
                  <input
                    type="number"
                    step="0.1"
                    className="input"
                    value={form.temperature}
                    onChange={e => set('temperature', Number(e.target.value) || 0)}
                  />
                </Field>
                <Field label="思考模式（DeepSeek）">
                  <select
                    className="input cursor-pointer"
                    value={form.think ? '1' : '0'}
                    onChange={e => set('think', e.target.value === '1')}
                  >
                    <option value="1">开启</option>
                    <option value="0">关闭</option>
                  </select>
                </Field>
                <Field label="推理强度（OpenAI）">
                  <select
                    className="input cursor-pointer"
                    value={form.reasoning_effort}
                    onChange={e => set('reasoning_effort', e.target.value)}
                  >
                    <option value="">不设置</option>
                    <option value="low">low</option>
                    <option value="medium">medium</option>
                    <option value="high">high</option>
                  </select>
                </Field>
                <Field label="审批等待超时（秒，0=无限）">
                  <input
                    type="number"
                    className="input"
                    value={form.approval_timeout}
                    onChange={e => set('approval_timeout', Number(e.target.value) || 0)}
                  />
                </Field>
                <Field label="超时后自动通过审批">
                  <select
                    className="input cursor-pointer"
                    value={form.approval_timeout_auto_approve ? '1' : '0'}
                    onChange={e => set('approval_timeout_auto_approve', e.target.value === '1')}
                  >
                    <option value="0">否</option>
                    <option value="1">是</option>
                  </select>
                </Field>
              </div>
            )}
          </div>
        </div>
      </Modal>
    </div>
  );
}

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: ReactNode;
}) {
  return (
    <div>
      <label className="mb-1 block text-xs font-medium text-zinc-500">
        {label}
        {required && <span className="ml-0.5 text-red-500">*</span>}
      </label>
      {children}
    </div>
  );
}
