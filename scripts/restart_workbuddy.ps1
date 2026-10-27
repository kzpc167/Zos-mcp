<#
重启 WorkBuddy。仅在明确需要时手动运行。

警告：
  本脚本会关闭 WorkBuddy 主程序，当前进行中的对话会被中断。
  请不要在对话正在跑任务时运行；先让任务结束，或确认可以中断。

注意：
  如果目的只是让 tools.py 的改动生效，**不需要用本脚本** ——
  mcp_server.py 已支持热加载，改完 tools.py 后下一次工具调用就会自动重载。

用法：
  powershell -ExecutionPolicy Bypass -File restart_workbuddy.ps1
  powershell -ExecutionPolicy Bypass -File restart_workbuddy.ps1 -DelaySeconds 15
  powershell -ExecutionPolicy Bypass -File restart_workbuddy.ps1 -Force          # 不询问
#>
param(
    [int]$DelaySeconds = 8,
    [switch]$Force,
    [string]$ExePath = "D:\Program Files\WorkBuddy\WorkBuddy.exe"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $ExePath)) {
    Write-Host "找不到 WorkBuddy.exe：$ExePath" -ForegroundColor Red
    Write-Host "请用 -ExePath 指定正确路径。" -ForegroundColor Red
    exit 1
}

if (-not $Force) {
    Write-Host "即将在 $DelaySeconds 秒后关闭并重启 WorkBuddy。" -ForegroundColor Yellow
    Write-Host "当前进行中的对话会被中断。按 Ctrl+C 取消。" -ForegroundColor Yellow
}

# 1) 延时，给当前任务留出收尾时间
if ($DelaySeconds -gt 0) {
    Start-Sleep -Seconds $DelaySeconds
}

# 2) 先尝试优雅关闭（发 WM_CLOSE），再兜底强杀
$procs = Get-Process -Name "WorkBuddy" -ErrorAction SilentlyContinue
if ($procs) {
    Write-Host ("关闭 {0} 个 WorkBuddy 进程…" -f $procs.Count)
    foreach ($p in $procs) {
        try { $p.CloseMainWindow() | Out-Null } catch { }
    }

    $deadline = (Get-Date).AddSeconds(8)
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-Process -Name "WorkBuddy" -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Milliseconds 500
    }

    $left = Get-Process -Name "WorkBuddy" -ErrorAction SilentlyContinue
    if ($left) {
        Write-Host ("仍有 {0} 个进程未退出，强制结束。" -f $left.Count) -ForegroundColor Yellow
        $left | Stop-Process -Force
        Start-Sleep -Seconds 2
    }
}
else {
    Write-Host "WorkBuddy 未在运行，直接启动。" -ForegroundColor Yellow
}

# 3) 重新拉起
Write-Host "启动 WorkBuddy…"
Start-Process -FilePath $ExePath
Start-Sleep -Seconds 2

if (Get-Process -Name "WorkBuddy" -ErrorAction SilentlyContinue) {
    Write-Host "已重启完成。" -ForegroundColor Green
}
else {
    Write-Host "启动失败，请手动打开 WorkBuddy。" -ForegroundColor Red
    exit 1
}
