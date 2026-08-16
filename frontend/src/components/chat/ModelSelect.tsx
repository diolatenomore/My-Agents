import { useAppStore } from '../../stores/appStore';

export default function ModelSelect() {
  const models = useAppStore(s => s.models);
  const modelsLoading = useAppStore(s => s.modelsLoading);
  const selectedModelId = useAppStore(s => s.selectedModelId);
  const selectModel = useAppStore(s => s.selectModel);

  return (
    <select
      className="input w-52 cursor-pointer py-1.5 text-[13px]"
      value={selectedModelId}
      title={selectedModelId ? `模型 ID：${selectedModelId}` : undefined}
      onChange={e => selectModel(e.target.value)}
    >
      {models.length === 0 && (
        <option value="">{modelsLoading ? '加载模型中…' : '未配置模型'}</option>
      )}
      {models.map(m => (
        <option key={m.id} value={m.id}>
          {m.name}（{m.model}）
        </option>
      ))}
    </select>
  );
}
