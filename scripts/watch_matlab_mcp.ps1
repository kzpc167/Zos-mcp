<#
Monitor MATLAB MCP server logs and prompt for a VS Code-managed restart.

Run from the repository root:
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch_matlab_mcp.ps1

Keep this PowerShell window open. The watcher only checks log entries written
after it starts; it does not stop or restart any process.
#>
param(
    [ValidateRange(1, 60)]
    [int]$PollIntervalSeconds = 2,
    [string]$LogDirectoryPath
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($LogDirectoryPath)) {
    $repoRoot = Split-Path -Parent $PSScriptRoot
    $LogDirectoryPath = Join-Path $repoRoot "matlab-mcp\logs"
}
$logDirectory = $LogDirectoryPath
$alertLogPath = Join-Path $logDirectory "watchdog-alerts.log"
$offsets = @{}
$lastAlerts = @{}
$failurePatterns = @(
    @{ Pattern = '(?i)timeout waiting for worker to start'; Label = "MATLAB worker startup timed out" },
    @{ Pattern = '(?i)timeout waiting for matlab to be ready'; Label = "MATLAB readiness timed out" },
    @{ Pattern = '(?i)MATLAB eager initialization failed'; Label = "MATLAB eager initialization failed" },
    @{ Pattern = '(?i)failed to attach to MATLAB session'; Label = "Failed to attach to the shared MATLAB session" },
    @{ Pattern = '(?i)dial tcp \[::1\].*(connection refused|actively refused)'; Label = "IPv6 localhost connection was refused" }
)

if (-not (Test-Path -LiteralPath $logDirectory -PathType Container)) {
    throw "MATLAB MCP log directory not found: $logDirectory"
}

Get-ChildItem -LiteralPath $logDirectory -Filter "server-*.log" -File |
    ForEach-Object { $offsets[$_.FullName] = $_.Length }

Write-Host "Monitoring MATLAB MCP logs: $logDirectory"
Write-Host "On a connection failure, use VS Code: MCP: List Servers > MATLAB > Restart."
Write-Host "Press Ctrl+C to stop."

while ($true) {
    foreach ($file in Get-ChildItem -LiteralPath $logDirectory -Filter "server-*.log" -File) {
        $path = $file.FullName

        if (-not $offsets.ContainsKey($path)) {
            $offsets[$path] = 0
        }
        elseif ($file.Length -lt $offsets[$path]) {
            $offsets[$path] = 0
        }

        if ($file.Length -le $offsets[$path]) {
            continue
        }

        $stream = [System.IO.File]::Open(
            $path,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,
            [System.IO.FileShare]::ReadWrite
        )
        try {
            [void]$stream.Seek($offsets[$path], [System.IO.SeekOrigin]::Begin)
            $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8, $true)
            try {
                $newContent = $reader.ReadToEnd()
                $offsets[$path] = $stream.Position
            }
            finally {
                $reader.Dispose()
            }
        }
        finally {
            $stream.Dispose()
        }

        foreach ($line in ($newContent -split "`r?`n")) {
            foreach ($failure in $failurePatterns) {
                if ($line -match $failure.Pattern) {
                    $alertKey = "$path|$($failure.Label)"
                    $now = Get-Date
                    if ($lastAlerts.ContainsKey($alertKey) -and
                        ($now - $lastAlerts[$alertKey]).TotalSeconds -lt 60) {
                        break
                    }

                    $lastAlerts[$alertKey] = $now
                    $alert = "[{0}] {1} in {2}" -f $now.ToString("yyyy-MM-dd HH:mm:ss"), $failure.Label, $file.Name
                    Add-Content -LiteralPath $alertLogPath -Value $alert -Encoding UTF8
                    Write-Host "`n$alert" -ForegroundColor Yellow
                    Write-Host "Please restart MATLAB MCP in VS Code: MCP: List Servers > MATLAB > Restart." -ForegroundColor Yellow
                    break
                }
            }
        }
    }

    Start-Sleep -Seconds $PollIntervalSeconds
}
