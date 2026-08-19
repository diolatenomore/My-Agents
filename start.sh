#!/usr/bin/env bash
# ============================================================
# my-agents 一键启动脚本 (macOS / Linux)
# 自动创建虚拟环境 -> 安装依赖 -> 构建前端 -> 启动后端
# 用法: ./start.sh [port]   # 如 ./start.sh 9000
# ============================================================
set -e
cd "$(dirname "$0")"

PORT="${1:-8000}"

echo "============================================================"
echo " my-agents - 一键启动 (生产/本地验证模式)"
echo "============================================================"

# ---- 1. 检查 Python ----
if ! command -v python3 >/dev/null 2>&1; then
    echo "[错误] 请先安装 Python 3.11+ 并加入 PATH"
    exit 1
fi

# ---- 2. 创建虚拟环境 ----
if [ ! -f ".venv/bin/activate" ]; then
    echo "[1/4] 创建虚拟环境 .venv ..."
    python3 -m venv .venv
else
    echo "[1/4] 虚拟环境已存在，跳过创建"
fi

source .venv/bin/activate

# ---- 3. 安装后端依赖 ----
echo "[2/4] 安装后端依赖 ..."
python -m pip install -r requirements.txt

# ---- 4. 安装前端依赖并构建 ----
cd frontend
echo "[3/4] 安装前端依赖 ..."
npm install
echo "[4/4] 构建前端生产产物 ..."
npm run build
cd ..

# ---- 5. 启动后端（托管构建产物） ----
echo "------------------------------------------------------------"
echo " 启动完成！访问 http://localhost:${PORT}"
echo " 按 Ctrl+C 停止服务"
echo "------------------------------------------------------------"
python -m src.main --port "$PORT"