export class ApiError extends Error {
  status: number;
  payload: unknown;

  constructor(message: string, status: number, payload?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload;
  }
}

/**
 * 统一 fetch 封装：自动解析 JSON，非 2xx 抛 ApiError（优先取后端 message）。
 * 注意后端响应格式不统一：/api/sessions 与 /api/models 返回裸数组，其余为 {code, message, ...}。
 */
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch (err) {
    throw new ApiError('网络错误，无法连接服务器', 0, err);
  }
  const text = await res.text();
  let data: unknown;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = undefined;
    }
  }
  if (!res.ok) {
    const message =
      (data as { message?: string } | undefined)?.message ?? `请求失败（HTTP ${res.status}）`;
    throw new ApiError(message, res.status, data);
  }
  return data as T;
}
