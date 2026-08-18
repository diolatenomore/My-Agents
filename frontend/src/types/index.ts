// ===== 通用 =====

export interface ApiEnvelope {
  code?: number;
  message?: string;
}

// ===== 会话 =====

export interface SessionDTO {
  session_id: string;
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
  project_id?: string | null;
}

// ===== 项目 =====

export interface ProjectDTO {
  project_id: string;
  name: string;
  work_dir: string;
  session_count: number;
  created_at: string;
  updated_at: string;
}

export interface ProjectFormValues {
  name: string;
  work_dir: string;
}

export interface ToolCallRecord {
  id: string;
  name: string;
  args: unknown;
}

/** GET /api/sessions/{sid}/messages 返回的单条历史消息 */
export interface StoredMessage {
  role: 'system' | 'user' | 'assistant' | 'tool';
  /** user 消息为 segments 数组格式（含 skill 占位符），其余角色为字符串 */
  content: string | SkillSegment[] | null;
  reasoning_content?: string | null;
  tool_calls?: ToolCallRecord[];
  tool_call_id?: string;
  cancelled?: boolean;
  _compaction_summary?: boolean;
}

export interface SessionMessagesResponse {
  session_id: string;
  messages: StoredMessage[];
  context_tokens: number;
}

export interface SubagentMessagesResponse {
  tool_call_id: string;
  messages: StoredMessage[];
}

// ===== 模型 =====

export interface ModelConfig {
  id: string;
  name: string;
  base_url: string;
  model: string;
  env_var_name: string;
  is_active: number;
  max_context_tokens: number;
  max_output_tokens: number;
  max_tool_calls: number;
  temperature: number;
  max_iterations: number;
  think: number;
  reasoning_effort: string | null;
  approval_timeout: number | null;
  approval_timeout_auto_approve: boolean;
  created_at: string;
  updated_at: string;
}

export interface ModelFormValues {
  name: string;
  base_url: string;
  model: string;
  api_key: string;
  max_context_tokens: number;
  max_output_tokens: number;
  max_tool_calls: number;
  temperature: number;
  max_iterations: number;
  think: boolean;
  reasoning_effort: string;
  approval_timeout: number;
  approval_timeout_auto_approve: boolean;
}

// ===== 记忆 =====

export type MemoryType = 'preference' | 'semantic';

export interface MemoryItem {
  id: string;
  memory_type: MemoryType;
  value: string;
  key: string;
  session_id: string;
  created_at: string;
}

export interface MemoryListResponse {
  items: MemoryItem[];
  total: number;
  limit: number;
  offset: number;
}

// ===== 技能 =====

export interface SkillInfo {
  name: string;
  description?: string;
  version?: string;
  tags?: string[];
  disabled?: boolean;
}

/** 用户消息的展示分段：文字段或 skill 占位符（chip 位置 = 数组顺序） */
export type SkillSegment =
  | { type: 'text'; text: string }
  | { type: 'skill'; name: string };

/** 把展示分段拼接为纯文本（skill 段不贡献字符，前后空白归一化） */
export function joinSegments(segments: SkillSegment[]): string {
  const text = segments
    .map(seg => (seg.type === 'text' ? seg.text : ' '))
    .join('');
  return text.replace(/[^\S\n]+/g, ' ').replace(/ ?\n ?/g, '\n').trim();
}

// ===== VFS 文件变更审批 =====

export type VfsOpType =
  | 'MKDIR'
  | 'DELETE_DIR'
  | 'RENAME_DIR'
  | 'CREATE_FILE'
  | 'DELETE_FILE'
  | 'MODIFY_FILE'
  | 'RENAME_FILE';

export interface ReviewItem {
  id: string;
  op_type: VfsOpType;
  source: string;
  target?: string | null;
  copy_source?: string | null;
  status?: string;
  children?: ReviewItem[];
}

export interface ReviewTree {
  task_id?: string;
  items: ReviewItem[];
}

export interface ReviewDiffLine {
  type: 'same' | 'add' | 'del';
  text: string;
}

export interface ReviewContent {
  op_type: VfsOpType;
  source: string;
  target: string;
  before: string;
  after: string;
  diff: ReviewDiffLine[] | null;
}

// ===== SSE 流式事件（POST /api/chat/stream）=====

export type StreamEvent =
  | { type: 'session_ready'; session_id: string }
  | { type: 'thinking'; content: string }
  | { type: 'token'; content: string }
  | {
      type: 'tool_call';
      name: string;
      args: unknown;
      requires_approval?: boolean;
      tool_call_id?: string;
    }
  | {
      type: 'threshold_tool_call';
      name: string;
      args: unknown;
      tool_call_id: string;
      current_tool_calls: number;
      max_tool_calls: number;
    }
  | {
      type: 'threshold_iteration';
      tool_call_id: string;
      current_iterations: number;
      max_iterations: number;
    }
  | { type: 'tool_result'; name: string; result: string; tool_call_id?: string }
  | {
      type: 'done';
      content?: string;
      context_tokens?: number;
      finish_reason?: 'length';
      stop_reason?: 'max_iterations';
      review_tree?: ReviewTree | null;
    }
  | { type: 'cancelled'; content?: string; context_tokens?: number; review_tree?: ReviewTree | null }
  | { type: 'error'; message: string };

// ===== 聊天展示模型（前端渲染用）=====

export type TurnStatus = 'streaming' | 'done' | 'cancelled' | 'error';

export interface ThinkingBlockView {
  kind: 'thinking';
  id: string;
  content: string;
  streaming: boolean;
}

export interface TextBlockView {
  kind: 'text';
  id: string;
  content: string;
}

export interface ToolBlockView {
  kind: 'tool';
  id: string;
  name: string;
  args: unknown;
  toolCallId?: string;
  status: 'awaiting' | 'running' | 'done';
  result?: string;
  /** 需要审批时的审批类型 */
  approvalKind?: 'normal' | 'threshold';
  threshold?: { current: number; max: number };
  decision?: { approved: boolean; raisedBy?: number };
}

export interface IterationBlockView {
  kind: 'iteration';
  id: string;
  toolCallId: string;
  current: number;
  max: number;
  decision?: { approved: boolean; raisedBy?: number };
}

export interface ErrorNoteBlockView {
  kind: 'error-note';
  id: string;
  message: string;
}

export type TurnBlockView =
  | ThinkingBlockView
  | TextBlockView
  | ToolBlockView
  | IterationBlockView
  | ErrorNoteBlockView;

export interface UserEntry {
  kind: 'user';
  id: string;
  content: string;
  /** 带 skill 占位符时的展示分段（content 为其纯文本投影） */
  segments?: SkillSegment[];
}

export interface TurnEntry {
  kind: 'turn';
  id: string;
  blocks: TurnBlockView[];
  status: TurnStatus;
  /** 结束时的附加说明（输出达到上限 / 已达迭代上限等） */
  note?: string;
}

export type ChatEntry = UserEntry | TurnEntry;

// ===== Todo（从 todo 工具结果解析）=====

export type TodoStatus = 'pending' | 'in_progress' | 'completed' | 'cancelled';

/**
 * 后端 schema 声明字段为 content，但模型实际常传 text，工具结果会原样回显，
 * 因此两种字段名都兼容；status 可省略（后端默认 pending）。
 */
export interface TodoItem {
  id: string | number;
  text: string;
  status?: TodoStatus;
}

export interface TodoPayload {
  todos?: Array<{ id?: string | number; text?: string; content?: string; status?: string }>;
  summary?: string;
}
