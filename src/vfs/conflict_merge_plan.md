# VFS 冲突合并方案

## 背景

当两个不同 session/task 对同一文件进行了 VFS 操作并都尝试 apply 时，后 apply 的 task 可能静默覆盖先 apply 的结果。需要冲突检测与合并机制。

## 核心思路

冲突检测不需要跨 task 分析 diff_table，只需在 execute 阶段按需保存原始文件副本（base），apply 阶段对比 base 与当前磁盘文件即可。

## execute 阶段（modify_file）

```
1. 先在 staging_records 中检查是否有其他 task_id 也注册了同一 path
   - 查询: SELECT COUNT(*) FROM staging_records WHERE path = ? AND task_id != ? AND deleted = 0
   
2. copy(path, staging_path)  # 复制原文件到暂存区

3. 如果有其他 task 也在操作同一文件（count > 0）:
   - 保存原始副本作为三路合并的 base
   - 不追加的情况: 已审批通过的 task 会被 _clean_vfs_state 清理出 staging_records，无需额外处理

4. 在 staging_path 上执行修改（SEARCH/REPLACE 或全量覆盖）

5. 写入 diff_table
```

## apply 阶段（_apply_operation）

```
MODIFY_FILE 操作:

1. 检查 base 是否存在
   - 不存在 → 无潜在冲突，直接 copy staging_path → 磁盘，流程结束

2. 存在 → 读取 base 文件内容，计算 hash
   对比当前磁盘文件的 hash:
   - hash 一致 → 另一个 task 未 apply，无实际冲突，直接 copy staging_path → 磁盘
   - hash 不一致 → 另一个 task 已 apply，触发三路合并

3. 三路合并:
   - base   = base 的文件内容（原始文件）
   - ours   = staging_path 的文件内容（我们的修改结果）
   - theirs = 磁盘当前文件内容（另一个 task 的修改结果）
   
4. 调用 merge3.Merge3(base_lines, ours_lines, theirs_lines)
   - merge_lines() 输出合并结果
   - 无冲突 → 直接写入磁盘
   - 有冲突 → 写入 staging_path（带冲突标记），标记审批项状态为"待用户解决冲突"

5. 清理 base 文件
```

## 三路合并实现

使用 `merge3` 库（pip install merge3），无需手动实现：

```python
from merge3 import Merge3

base_lines   = open(staging_path + ".base").readlines()  # 原始文件
ours_lines   = open(staging_path).readlines()             # 我们的修改
theirs_lines = open(disk_path).readlines()                # 另一个 task 的结果

m3 = Merge3(base_lines, ours_lines, theirs_lines)
merged_lines = list(m3.merge_lines())

has_conflict = any(line.startswith('<<<<<<<') for line in merged_lines)
```

能自动合并的场景（双方修改不重叠 / 相同修改 / 仅一方修改）会自动合并；双方修改重叠的行会生成 `<<<<<<<` / `=======` / `>>>>>>>` 冲突标记。

## 冲突文件处理

- 带冲突标记的合并结果写回暂存区
- 用户在 IDE（VSCode 等）中使用内置冲突解决面板处理
- 解决后重新提交 apply

## 当前范围

仅处理 `MODIFY_FILE` vs `MODIFY_FILE` 场景。以下场景暂不处理：
- DELETE_FILE / RENAME_FILE 与其他操作的冲突
- 目录级别操作的冲突

## 依赖

- `merge3`（pip 依赖，GPL-2.0）
