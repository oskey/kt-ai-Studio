<# ComfyUI 启动脚本（美化版）- 支持中文显示 & 交互选择（多 Python 共存防串版） #>

# 基础编码配置（确保中文正常显示，不修改）
chcp 65001 > $null
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot  # 锁定脚本所在目录（ComfyUI根目录）

# ============================ 【1. 美化标题栏】 ============================
Write-Host "`n" -NoNewline
Write-Host "          ComfyUI 启动脚本 | 加速库选择工具          " -ForegroundColor White -BackgroundColor Cyan
Write-Host "`n" -NoNewline

# ============================ 【2. 虚拟环境检测 + 强制锁定 Python】 ============================
Write-Host "🔍 正在检测虚拟环境...`n" -ForegroundColor Cyan

$venvActivate = ".\comfyui_venv\Scripts\Activate.ps1"
$venvPython   = ".\comfyui_venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "❌ 错误：未找到虚拟环境 Python：$venvPython" -ForegroundColor Red
    Write-Host "   请先运行安装脚本创建 comfyui_venv 后再启动！`n" -ForegroundColor Red
    Pause
    exit 1
}

# 校验 venv Python 版本必须为 3.13（避免串到 3.10）
try {
    $venvVer = (& $venvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')").Trim()
} catch {
    Write-Host "❌ 错误：无法运行 $venvPython，请检查虚拟环境是否损坏" -ForegroundColor Red
    Pause
    exit 1
}

if (-not $venvVer.StartsWith("3.13.")) {
    Write-Host "❌ 错误：comfyui_venv 的 Python 版本不是 3.13（当前：$venvVer）" -ForegroundColor Red
    Write-Host "   这通常表示 venv 创建时用错了解释器，请删除 comfyui_venv 后用安装脚本重建。" -ForegroundColor Yellow
    Pause
    exit 1
}

Write-Host "✅ 检测到 comfyui_venv (Python $venvVer)" -ForegroundColor Green
Write-Host "✅ 将强制使用：$venvPython`n" -ForegroundColor Cyan

# 可选：激活环境（不是必须，但保留以兼容部分依赖）
if (Test-Path $venvActivate) {
    . $venvActivate
    Write-Host "✅ 虚拟环境激活成功！`n" -ForegroundColor Green
} else {
    Write-Host "⚠️ 未找到 Activate.ps1，将直接用 venv python 启动（不影响正常运行）`n" -ForegroundColor Yellow
}

# ============================ 【3. 加速库选择（美化选项）】 ============================
Write-Host "📌 请选择加速库（按对应数字后回车）：" -ForegroundColor Cyan
Write-Host "   [1] " -ForegroundColor Green -NoNewline
Write-Host "FlashAttention " -ForegroundColor White -NoNewline
Write-Host "| 推荐高速 | 默认选项" -ForegroundColor Gray
Write-Host "   [2] " -ForegroundColor Green -NoNewline
Write-Host "SageAttention 2.2 " -ForegroundColor White -NoNewline
Write-Host "| 低显存优化 | int8支持" -ForegroundColor Gray
Write-Host "   [3] " -ForegroundColor Green -NoNewline
Write-Host "ComfyUI 自带加速 " -ForegroundColor White -NoNewline
Write-Host "| 兼容性优先" -ForegroundColor Gray
Write-Host "`n" -NoNewline

$accelChoice = Read-Host "👉 请输入 1/2/3（直接回车默认选择 1）"
if ([string]::IsNullOrEmpty($accelChoice)) { $accelChoice = "1" }

# ============================ 【4. 选项确认（带动态加载）】 ============================
Write-Host "`n" -NoNewline
Write-Host "⚙️  正在确认选择" -ForegroundColor Cyan
for ($i=1; $i -le 3; $i++) {
    Write-Host "." -NoNewline -ForegroundColor Cyan
    Start-Sleep -Milliseconds 300
}
Write-Host "`n" -NoNewline

switch ($accelChoice) {
    "1" {
        $accelParam = "--use-flash-attention"
        Write-Host "✅ 已选择：FlashAttention 加速（推荐）`n" -ForegroundColor Green
    }
    "2" {
        $accelParam = "--use-sage-attention"
        Write-Host "✅ 已选择：SageAttention 2.2 加速（低显存）`n" -ForegroundColor Green
    }
    "3" {
        $accelParam = ""
        Write-Host "✅ 已选择：ComfyUI 自带加速（兼容）`n" -ForegroundColor Green
    }
    default {
        $accelParam = "--use-flash-attention"
        Write-Host "⚠️  输入无效（仅支持1/2/3），已默认选择：FlashAttention 加速`n" -ForegroundColor Yellow
    }
}

# ============================ 【6. 启动 ComfyUI（强制用 venv python）】 ============================
Write-Host "🚀 正在启动 ComfyUI..." -ForegroundColor Cyan
Write-Host "   访问地址：http://localhost:8188 或 http://你的IP:8188`n" -ForegroundColor Gray

# 关键：用 venv 的 python.exe 启动，彻底避免 3.10/3.13 串环境
& $venvPython main.py --listen "0.0.0.0" --port "8188" $accelParam

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n🎉 成功：ComfyUI 已正常启动！关闭此窗口将停止服务`n" -ForegroundColor Green
} else {
    Write-Host "`n❌ 失败：ComfyUI 启动出错！请检查依赖包或 CUDA 配置`n" -ForegroundColor Red
}

Pause
