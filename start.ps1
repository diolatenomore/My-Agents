# ============================================================
# my-agents 一键启动脚本 (Windows PowerShell)
# 自动创建虚拟环境 -> 安装依赖 -> 构建前端 -> 启动后端
# 用法: .\start.ps1 [-Port 9000]
# ============================================================
param([int]$Port = 8000)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

function Read-Stop([string]$msg) {
    Write-Host "[错误] $msg"
    Read-Host "按回车退出..."
    exit 1
}

Write-Host "============================================================"
Write-Host " my-agents - 一键启动 (生产/本地验证模式)"
Write-Host "============================================================"

# ---- 1. 检查 Python ----
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Read-Stop "未找到 python，请先安装 Python 3.11+ 并加入 PATH"
}

# ---- 2. 创建虚拟环境 ----
$venvActivate = Join-Path $PSScriptRoot ".venv\Scripts\Activate.ps1"
if (-not (Test-Path $venvActivate)) {
    Write-Host "[1/4] 创建虚拟环境 .venv ..."
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { Read-Stop "创建虚拟环境失败" }
} else {
    Write-Host "[1/4] 虚拟环境已存在，跳过创建"
}

& $venvActivate

# ---- 3. 安装后端依赖 ----
Write-Host "[2/4] 安装后端依赖 ..."
python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { Read-Stop "后端依赖安装失败" }

# ---- 4. 安装前端依赖并构建 ----
Set-Location frontend
Write-Host "[3/4] 安装前端依赖 ..."
npm install
if ($LASTEXITCODE -ne 0) { Read-Stop "前端依赖安装失败" }
Write-Host "[4/4] 构建前端生产产物 ..."
npm run build
if ($LASTEXITCODE -ne 0) { Read-Stop "前端构建失败" }
Set-Location $PSScriptRoot

# ---- 5. 启动后端（托管构建产物） ----
Write-Host "------------------------------------------------------------"
Write-Host " 启动完成！访问 http://localhost:$Port"
Write-Host " 按 Ctrl+C 停止服务"
Write-Host "------------------------------------------------------------"
python -m src.main --port $Port