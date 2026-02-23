<#
ComfyUI 安装脚本（PowerShell 版）
环境：Python 3.13.x + CUDA 13.0
虚拟环境：comfyui_venv
功能：
- 支持选择 PyTorch 2.9.0 或 2.10 (Nightly) 版本
- 强制使用 Python 3.13（兼容系统同时装有 3.10/3.13）
- uv 虚拟环境创建与依赖安装
- 可选安装 Triton/FlashAttention/SageAttention
#>

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "`n🚀 开始安装 ComfyUI 环境 (Python 3.13 + CUDA 13.0)" -ForegroundColor Cyan

# === 选择并锁定 Python 3.13 解释器 ======================================
function Get-Python313Path {
    # 需要系统已安装 py launcher（你现在有）
    $py = Get-Command py -ErrorAction SilentlyContinue
    if (-not $py) {
        throw "未检测到 py launcher。请安装 Python 时勾选 'Install launcher for all users' 或手动安装 Python Launcher。"
    }

    # 获取 3.13 解释器路径
    $path = & py -3.13 -c "import sys; print(sys.executable)"
    if (-not $path -or -not (Test-Path $path)) {
        throw "未找到 Python 3.13 解释器路径。请确认已安装 Python 3.13 (64-bit)。"
    }
    return $path.Trim()
}

$PY313 = Get-Python313Path
Write-Host "✅ 已锁定 Python 3.13 解释器: $PY313" -ForegroundColor Cyan

# === 系统 Python 版本检测（严格用 3.13 跑检测） ==========================
$verOK = & $PY313 -c "import sys; print(int(sys.version_info >= (3,13,0)))"
if ($verOK.Trim() -ne "1") {
    $sys_pyver = & $PY313 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
    Write-Host "❌ 当前 Python 版本为 $sys_pyver，需要 Python 3.13.x" -ForegroundColor Red
    exit 1
} else {
    $sys_pyver = & $PY313 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
    Write-Host "✅ 系统 Python 版本为 $sys_pyver" -ForegroundColor Cyan
}

# === 检查 uv ============================================================
# 说明：uv 是独立工具，通常安装后会在 PATH；若没有，就用 3.13 的 pip 安装一次
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "⚙️ 未检测到 uv，正在使用 Python 3.13 安装 uv..." -ForegroundColor Yellow
    & $PY313 -m pip install -U uv
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv 安装后仍未在 PATH 中找到。请重开终端或把 Python Scripts 目录加入 PATH。"
    }
}
Write-Host "✅ uv 已就绪: $((Get-Command uv).Source)" -ForegroundColor Cyan

# === 检查并处理旧虚拟环境 ==============================================
$venvPath = ".\comfyui_venv"
$venvExists = Test-Path $venvPath

if ($venvExists) {
    $choice = Read-Host "⚠️ 检测到已存在 comfyui_venv，是否删除并重新安装？(Y/N)"
    if ($choice -match '^[Yy]$') {
        Write-Host "🧹 正在删除旧的虚拟环境..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force $venvPath -ErrorAction Stop
        $venvExists = $false
    } else {
        Write-Host "⏭️ 保留原有虚拟环境，激活并继续..." -ForegroundColor Gray
        & "$venvPath\Scripts\Activate.ps1"
        if (-not $?) {
            Write-Host "❌ 激活现有虚拟环境失败，可能环境已损坏，请删除后重装" -ForegroundColor Red
            exit 1
        }
    }
}

# === 创建虚拟环境（强制用 Python 3.13 路径创建） =========================
if (-not $venvExists) {
    Write-Host "✅ 创建虚拟环境 comfyui_venv (使用 Python 3.13)" -ForegroundColor Cyan
    uv venv comfyui_venv --python "$PY313"
    if (-not $?) {
        Write-Host "❌ 创建虚拟环境失败，请检查权限或删除残留文件后重试" -ForegroundColor Red
        exit 1
    }

    & "$venvPath\Scripts\Activate.ps1"
    if (-not $?) {
        Write-Host "❌ 激活新虚拟环境失败" -ForegroundColor Red
        exit 1
    }

    # === 修复 pip（仅新环境需要） ======================================
    Write-Host "🩹 检查并升级 pip, setuptools, wheel..." -ForegroundColor Yellow
    python -m ensurepip --upgrade | Out-Null
    python -m pip install -U pip setuptools wheel
}

# === 校验虚拟环境 Python 版本（确保就是 3.13） ==========================
$venv_python = "$venvPath\Scripts\python.exe"
$venv_ver = & $venv_python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($venv_ver.Trim() -ne "3.13") {
    Write-Host "❌ 虚拟环境 Python 版本不是 3.13（实际: $venv_ver），请删除 comfyui_venv 后重建" -ForegroundColor Red
    exit 1
} else {
    Write-Host "✅ 虚拟环境 Python 版本为 $venv_ver" -ForegroundColor Cyan
}

# === 选择 PyTorch 版本 ================================================
Write-Host "`n请选择 PyTorch 版本：" -ForegroundColor Cyan
Write-Host "1: PyTorch 2.9.0"
Write-Host "2: PyTorch 2.10 (Nightly)"
$pytorchChoice = Read-Host "请输入选项 (1/2)"

$torchInstallCmd = ""
$flashUrl = ""
$flashFile = ""
$sageUrl = ""
$sageFile = ""

switch ($pytorchChoice) {
    "1" {
        Write-Host "`n📌 已选择 PyTorch 2.9.0" -ForegroundColor Green
        $torchInstallCmd = "uv pip install torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cu130"
        $flashUrl  = "https://huggingface.co/Wildminder/AI-windows-whl/resolve/main/flash_attn-2.8.3+cu130torch2.9.0cxx11abiTRUE-cp313-cp313-win_amd64.whl"
        $flashFile = "flash_attn-2.8.3+cu130torch2.9.0cxx11abiTRUE-cp313-cp313-win_amd64.whl"
        $sageUrl   = "https://huggingface.co/Wildminder/AI-windows-whl/resolve/main/sageattention-2.2.0.post3+cu130torch2.9.0-cp313-cp313-win_amd64.whl"
        $sageFile  = "sageattention-2.2.0.post3+cu130torch2.9.0-cp313-cp313-win_amd64.whl"
    }
    "2" {
        Write-Host "`n📌 已选择 PyTorch 2.10 (Nightly)" -ForegroundColor Green
        $torchInstallCmd = "uv pip install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/cu130"
        $flashUrl  = "https://huggingface.co/Wildminder/AI-windows-whl/resolve/main/flash_attn-2.8.3+cu130torch2.10.0cxx11abiTRUE-cp313-cp313-win_amd64.whl"
        $flashFile = "flash_attn-2.8.3+cu130torch2.10.0cxx11abiTRUE-cp313-cp313-win_amd64.whl"
        $sageUrl   = "https://huggingface.co/Wildminder/AI-windows-whl/resolve/main/sageattention-2.2.0.post3+cu130torch2.10.0-cp313-cp313-win_amd64.whl"
        $sageFile  = "sageattention-2.2.0.post3+cu130torch2.10.0-cp313-cp313-win_amd64.whl"
    }
    default {
        Write-Host "❌ 无效选项，请输入 1 或 2" -ForegroundColor Red
        exit 1
    }
}

# === 安装 PyTorch =======================================================
Write-Host "`n📦 安装 PyTorch & TorchVision & Torchaudio (CUDA 13.0)" -ForegroundColor Green
Invoke-Expression $torchInstallCmd
if (-not $?) {
    Write-Host "❌ PyTorch 相关组件安装失败" -ForegroundColor Red
    exit 1
}

# === 下载函数 ===========================================================
function Download-IfMissing {
    param (
        [string]$Url,
        [string]$Filename,
        [string]$SHA256 = ""
    )

    if (-Not (Test-Path $Filename)) {
        $tmp = "$Filename.tmp"
        Write-Host "🌐 正在下载 $Filename ..." -ForegroundColor Green
        Invoke-WebRequest -Uri $Url -OutFile $tmp -UseBasicParsing -Verbose:$false

        if ($SHA256 -ne "") {
            $hash = Get-FileHash $tmp -Algorithm SHA256
            if ($hash.Hash -ne $SHA256) {
                Write-Host "❌ SHA256 校验失败: $Filename" -ForegroundColor Red
                Remove-Item $tmp
                throw "下载文件损坏或不完整，请重试！"
            }
        }

        Rename-Item $tmp $Filename
    } else {
        Write-Host "✅ 检测到本地缓存：$Filename" -ForegroundColor Gray
    }
}

# === 可选安装 Triton ====================================================
$installTriton = Read-Host "`n是否安装 Triton (Windows 兼容版)？(Y/N)"
if ($installTriton -match '^[Yy]$') {
    Write-Host "⚙️ 开始安装 Triton..." -ForegroundColor Green
    uv pip install -U "triton-windows<3.5"
    Write-Host "✅ Triton 安装完成！" -ForegroundColor Cyan
} else {
    Write-Host "⏭️ 跳过 Triton 安装" -ForegroundColor Gray
}

# === 可选安装 FlashAttention ============================================
$installFlash = Read-Host "`n是否安装 FlashAttention？(Y/N)"
if ($installFlash -match '^[Yy]$') {
    Download-IfMissing $flashUrl $flashFile
    uv pip install ".\$flashFile"
    Write-Host "✅ FlashAttention 安装完成！" -ForegroundColor Cyan
} else {
    Write-Host "⏭️ 跳过 FlashAttention 安装" -ForegroundColor Gray
}

# === 可选安装 SageAttention =============================================
$installSage = Read-Host "`n是否安装 SageAttention 2.2？(Y/N)"
if ($installSage -match '^[Yy]$') {
    Download-IfMissing $sageUrl $sageFile
    Write-Host "⚙️ 临时跳过 wheel 文件名检查..." -ForegroundColor Yellow
    $env:UV_SKIP_WHEEL_FILENAME_CHECK = "1"
    uv pip install ".\$sageFile"
    Remove-Item Env:\UV_SKIP_WHEEL_FILENAME_CHECK -ErrorAction SilentlyContinue
    Write-Host "✅ SageAttention 2.2 安装完成！" -ForegroundColor Cyan
} else {
    Write-Host "⏭️ 跳过 SageAttention 安装" -ForegroundColor Gray
}

# === 安装 ComfyUI requirements ==========================================
if (Test-Path "requirements.txt") {
    Write-Host "`n📘 安装 ComfyUI requirements.txt 依赖..." -ForegroundColor Green
    uv pip install -r requirements.txt
}

Write-Host ""
Write-Host "✅ 安装完成！" -ForegroundColor Cyan
Write-Host "➡️ ComfyUI 已成功安装完毕，请用 Start-ComfyUI.ps1 启动!" -ForegroundColor Cyan
