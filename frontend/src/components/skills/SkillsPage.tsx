import { useCallback, useEffect, useRef, useState } from 'react';
import { Package, RefreshCw, Sparkles, Upload } from 'lucide-react';
import type { SkillInfo } from '../../types';
import { listSkills, toggleSkill, uploadSkill } from '../../api/skills';
import { toast } from '../../stores/uiStore';
import { cn } from '../../utils/misc';
import PageHeader from '../common/PageHeader';
import EmptyState from '../common/EmptyState';
import Switch from '../common/Switch';
import Modal from '../common/Modal';

const MAX_UPLOAD_SIZE = 15 * 1024 * 1024; // 后端限制 15MB

export default function SkillsPage() {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [detail, setDetail] = useState<SkillInfo | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listSkills();
      if (data.code === 200) {
        setSkills(data.skills ?? []);
      }
    } catch (err) {
      toast('error', err instanceof Error ? err.message : '加载技能失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleToggle = async (skill: SkillInfo, disabled: boolean) => {
    try {
      const res = await toggleSkill(skill.name, disabled);
      if (res.code === 200) {
        setSkills(prev =>
          prev.map(s => (s.name === skill.name ? { ...s, disabled } : s)),
        );
        if (detail?.name === skill.name) setDetail({ ...detail, disabled });
        toast('success', disabled ? `已禁用 ${skill.name}` : `已启用 ${skill.name}`);
      } else {
        toast('error', res.message || '操作失败');
      }
    } catch (err) {
      toast('error', err instanceof Error ? err.message : '网络错误');
    }
  };

  const handleUpload = async (file: File) => {
    if (!file.name.toLowerCase().endsWith('.zip')) {
      toast('error', '只支持 .zip 格式的技能包');
      return;
    }
    if (file.size > MAX_UPLOAD_SIZE) {
      toast('error', '技能包不能超过 15MB');
      return;
    }
    setUploading(true);
    try {
      const res = await uploadSkill(file);
      if (res.code === 200) {
        toast('success', res.message || '上传成功');
        await load();
      } else {
        toast('error', res.message || '上传失败');
      }
    } catch (err) {
      toast('error', err instanceof Error ? err.message : '上传失败');
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  return (
    <div className="nice-scroll min-h-0 flex-1 overflow-y-auto bg-zinc-50">
      <div className="mx-auto w-full max-w-4xl px-6 py-6">
        <PageHeader
          icon={Sparkles}
          title="技能管理"
          subtitle={skills.length > 0 ? `共 ${skills.length} 个技能` : '上传 zip 技能包扩展 Agent 能力'}
          actions={
            <>
              <input
                ref={fileRef}
                type="file"
                accept=".zip"
                className="hidden"
                onChange={e => {
                  const f = e.target.files?.[0];
                  if (f) void handleUpload(f);
                }}
              />
              <button
                className="btn btn-primary"
                disabled={uploading}
                onClick={() => fileRef.current?.click()}
              >
                <Upload size={14} />
                {uploading ? '上传中…' : '上传技能'}
              </button>
              <button className="btn btn-outline" onClick={() => void load()} title="刷新">
                <RefreshCw size={14} className={cn(loading && 'animate-spin')} />
                刷新
              </button>
            </>
          }
        />

        <div className="space-y-2">
          {skills.length === 0 ? (
            <EmptyState
              icon={Package}
              title={loading ? '加载中…' : '暂无技能'}
              description={loading ? undefined : '上传包含 SKILL.md 的 .zip 技能包'}
            />
          ) : (
            skills.map(s => (
              <div
                key={s.name}
                className="card flex cursor-pointer items-start gap-3 px-4 py-3 transition-colors hover:border-indigo-200"
                onClick={() => setDetail(s)}
              >
                <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-zinc-100 text-zinc-500">
                  <Package size={17} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-zinc-800">{s.name}</span>
                    {s.version && (
                      <span className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[10px] text-zinc-500">
                        v{s.version}
                      </span>
                    )}
                  </div>
                  {s.description && (
                    <div className="mt-1 line-clamp-2 text-[13px] leading-relaxed text-zinc-500">
                      {s.description}
                    </div>
                  )}
                  {s.tags && s.tags.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {s.tags.map(t => (
                        <span
                          key={t}
                          className="rounded-full bg-indigo-50 px-2 py-0.5 text-[10px] text-indigo-600"
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <div className="flex shrink-0 items-center gap-2" onClick={e => e.stopPropagation()}>
                  <span className={cn('text-[11px]', s.disabled ? 'text-zinc-400' : 'text-emerald-600')}>
                    {s.disabled ? '已禁用' : '已启用'}
                  </span>
                  <Switch checked={!s.disabled} onChange={v => void handleToggle(s, !v)} />
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* 技能详情 */}
      <Modal open={detail !== null} title="技能详情" onClose={() => setDetail(null)} width="max-w-xl">
        {detail && (
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <span className="text-base font-semibold text-zinc-800">{detail.name}</span>
              {detail.version && (
                <span className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[11px] text-zinc-500">
                  v{detail.version}
                </span>
              )}
            </div>
            <div>
              <div className="mb-1 text-xs font-medium text-zinc-400">描述</div>
              <p className="text-sm leading-relaxed whitespace-pre-wrap text-zinc-600">
                {detail.description || '无'}
              </p>
            </div>
            <div>
              <div className="mb-1.5 text-xs font-medium text-zinc-400">标签</div>
              {detail.tags && detail.tags.length > 0 ? (
                <div className="flex flex-wrap gap-1">
                  {detail.tags.map(t => (
                    <span key={t} className="rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] text-indigo-600">
                      {t}
                    </span>
                  ))}
                </div>
              ) : (
                <span className="text-sm text-zinc-400">无</span>
              )}
            </div>
            <div className="flex items-center gap-2 rounded-lg bg-zinc-50 px-3 py-2.5">
              <Switch checked={!detail.disabled} onChange={v => void handleToggle(detail, !v)} />
              <span className={cn('text-[13px]', detail.disabled ? 'text-zinc-400' : 'text-emerald-600')}>
                {detail.disabled ? '已禁用' : '已启用'}
              </span>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
