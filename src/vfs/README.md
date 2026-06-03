# VFS (Virtual File System) 模块

VFS 模块为 AI 文件整理任务提供了一套**虚拟文件系统**机制。它通过**暂存区（Staging Area）**、**写时复制（Copy-on-Write）** 和**操作差分表（Diff Table）**，让 AI 工作流可以在不直接修改原始文件系统的情况下，安全地规划和执行文件整理操作，最终输出可审核、可回撤的**最简操作集**。

## 核心概念

在执行文件整理任务时，所有对文件/目录的修改操作不会直接作用到原始文件系统，而是被重定向到暂存区。同时，系统会记录每一步操作到差分表中，最终通过合并算法生成精简后的操作树。

整体流程：
1. **plan 阶段**：AI 读取目录结构、文件内容，制定整理计划
2. **execute 阶段**：AI 执行计划中的操作，所有变更记录到暂存区和差分表
3. **merge 阶段**：将操作记录合并为最简操作集，供用户审核确认
4. **apply 阶段**：将审核通过的操作真正应用到文件系统

## 模块组成

### 1. `task_context.py` —— 任务上下文

全局单例，用于在工作流中传递当前任务的 `task_id`。

- `TaskContent`：全局类级别的 `task_id` 持有者
- `get_current_task_id()`：获取当前任务 ID，未设置时抛出异常
- `set_current_task_id(task_id)`：设置当前任务 ID（重复设置会报错）
- `clean_current_task_id()`：清理任务 ID

### 2. `staging_area.py` —— 暂存区管理

核心暂存区机制，所有对文件系统的修改操作都在暂存区中进行映射。

- `StagingArea`：类级别的缓存，维护路径到暂存区路径的映射
  - `mapping`：`{原始路径 -> 暂存区路径}` 映射表
  - `deleted_mapping`：文件删除标记表
  - `deleted_dir_mapping`：目录删除标记表
- `register(path)`：为文件分配一条暂存区路径（基于 MD5 哈希 + 扩展名）
- `register_dir(path)`：为目录注册暂存区占位
- `delete(path)` / `delete_dir(path)`：在暂存区标记文件/目录为已删除
- `rename(old, new)` / `rename_dir(old, new)`：在暂存区中重命名路径
- `get_staging_path(path)`：获取文件的暂存区真实路径
- `load(task_id)` / `clear()`：从数据库加载/清空暂存区缓存

目录暂存区**不实际创建目录**，仅作为占位符（`staging_path = " "`），避免在文件系统中创建大量空目录。

### 3. `copy_mapping.py` —— 写时复制映射

实现**Copy-on-Write**机制。当文件被复制或移动时，不会立即拷贝文件内容，而是先注册复制记录。只有在原文件发生修改或删除时，才真正执行文件拷贝。

- `CopyMapping`：类级别的复制记录管理器
  - `register(source, target)`：注册文件复制记录
  - `register_dir(source, target)`：注册目录复制记录
  - `need_copied(path)`：判断原文件是否需要被拷贝
  - `mark_copied(path)`：执行拷贝并标记完成
  - `copy_if_need(target_path)`：按需判断目标路径是否需要拷贝
  - `rename(old, new)` / `rename_dir(old, new)`：更新映射关系
  - `load(task_id)`：从数据库加载复制记录

典型场景——`move_file` 操作：
1. 注册复制记录（`source -> target`）
2. 在暂存区标记 `source` 为已删除
3. 在暂存区为 `target` 分配路径
4. 如果后续 `source` 被修改，触发实际文件拷贝

### 4. `operations.py` —— 文件操作入口

提供 AI 工作流可直接调用的文件/目录操作函数。所有操作都会：

1. 检查路径合法性（命名冲突、存在性等）
2. 在暂存区注册/更新路径映射
3. 检查并触发写时复制
4. 写入操作记录到差分表

支持的操作：

| 操作 | 说明 |
|------|------|
| `list_dir(path)` | 列出目录内容（合并暂存区与真实文件系统） |
| `read_file(path)` | 读取文件内容（优先从暂存区读取） |
| `create_file(path, content)` | 在暂存区创建文件 |
| `delete_file(path)` | 在暂存区标记删除文件 |
| `rename_file(src, dst)` | 重命名文件（不支持跨目录） |
| `modify_file(path, content)` | 修改文件内容 |
| `copy_file(src, dst)` | 复制文件（写时复制机制） |
| `move_file(src, dst)` | 移动文件 |
| `mkdir(path)` | 创建空目录 |
| `delete_dir(path)` | 删除目录 |
| `rename_dir(src, dst)` | 重命名目录 |
| `copy_dir(src, dst)` | 复制目录 |
| `move_dir(src, dst)` | 移动目录 |

### 5. `diff_table.py` —— 操作差分表与合并

记录所有操作并生成可审核的最简操作集。

- `DiffRecord`：单条操作记录（包含 `task_id`, `operation_type`, `source_path`, `target_path`, `step`）
- `OperationType`：操作类型枚举
  - 文件级：`CREATE_FILE`, `DELETE_FILE`, `RENAME_FILE`, `MODIFY_FILE`
  - 目录级：`MKDIR`, `DELETE_DIR`, `RENAME_DIR`
- `DiffTable`：操作记录的存储、查询与合并
  - `operate(record)` / `operate_batch(records)`：写入操作记录
  - `list(task_id)`：查询任务的所有操作记录
  - `merge(records)`：**核心方法**，将操作记录合并为最简操作集

#### 合并算法（merge）

合并过程分为以下步骤：

**Step 1：反向遍历 + 路径映射**
- 从后向前遍历操作记录
- 处理重命名操作（`RENAME_FILE`, `RENAME_DIR`），建立路径映射关系
- 将映射应用到在它之前的操作记录上（实现链式重命名追踪）

**Step 2：按目录结构分组**
- 第一遍：提取目录级操作（MKDIR/DELETE_DIR/RENAME_DIR），构建目录树
- 第二遍：将文件级操作按所属目录分组

**Step 3：组内合并**
- 使用预定义的合并规则（`_match` 方法），对同一路径的多个操作进行合并
- 最终消除中间冗余操作，生成最简操作集

#### 合并规则示例

| 前操作 | 后操作 | 合并结果 |
|--------|--------|----------|
| MKDIR | RENAME_DIR | MKDIR（以最终路径为准） |
| MKDIR | DELETE_DIR | 取消（相互抵消） |
| DELETE_DIR | MKDIR | 取消（先删后建 = 修改） |
| CREATE_FILE | DELETE_FILE | 取消 |
| DELETE_FILE | CREATE_FILE | MODIFY_FILE |
| MODIFY_FILE | MODIFY_FILE | MODIFY_FILE |

## 数据流示例

以一次文件整理任务（如日志中的 `d43a4891-824c-41e5-81f4-292f53c1d151`）为例：

```
plan 阶段（只读）:
  list_dir("/test_dir") -> 获取文件/目录列表
  read_file("/test_dir/笔记.txt") -> 读取内容分析
  -> 输出整理计划

execute 阶段（写操作重定向）:
  mkdir("/test_dir/life")        -> staging_area.register_dir()
  move_file("/test_dir/健身记录.txt", "/test_dir/life/健身记录.txt")
    -> copy_mapping.register() + staging_area.delete() + staging_area.register()
    -> diff_table.operate_batch([CREATE_FILE, DELETE_FILE])
  ...

merge 阶段（生成最简操作集）:
  diff_table.merge(records) -> OperationTree
  # 输出精简后的操作树，供用户审核
```

合并后的最简操作集会像这样：

```
路径: /test_dir
  文件操作:
    健身记录.txt: DELETE_FILE
    旅行计划.txt: DELETE_FILE
  子目录:
    路径: /test_dir/life
      目录操作: MKDIR
      文件操作:
        life/健身记录.txt: CREATE_FILE
        life/旅行计划.txt: CREATE_FILE
```

## 数据库表说明

VFS 模块使用三个核心数据库表：

- `staging_records`：暂存区路径映射表（路径、暂存区路径、是否目录、是否删除）
- `copy_records`：复制记录表（源路径、目标路径、是否已拷贝、是否目录）
- `diff_records`：操作记录表（操作类型、源路径、目标路径、步骤、时间）