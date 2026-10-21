<#
  晚安成电 · 自动签到：安装 / 卸载 / 自检

  用法（在 PowerShell 里，或直接双击对应的 .bat）：
    powershell -ExecutionPolicy Bypass -File install_task.ps1
    powershell -ExecutionPolicy Bypass -File install_task.ps1 -Time 22:00
    powershell -ExecutionPolicy Bypass -File install_task.ps1 -RunNow
    powershell -ExecutionPolicy Bypass -File install_task.ps1 -SelfTest
    powershell -ExecutionPolicy Bypass -File install_task.ps1 -Remove
#>
[CmdletBinding()]
param(
    [string]$Time = "22:00",
    [string]$Time2 = "23:25",
    [switch]$Remove,
    [switch]$RunNow,
    [switch]$SelfTest,
    [switch]$Install
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TaskName = "WananChengdianSign"
$ScriptPath = Join-Path $AppDir "wechat_auto.py"

function Say([string]$Text, [string]$Color = "Gray") {
    Write-Host $Text -ForegroundColor $Color
}

if (-not (Test-Path $ScriptPath)) {
    Say "找不到 wechat_auto.py，请确认脚本和本文件在同一个文件夹。" "Red"
    exit 1
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

if ($Remove) {
    if ($existing) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Say "已删除计划任务：$TaskName" "Green"
    } else {
        Say "没有找到计划任务 $TaskName，无需删除。"
    }
    exit 0
}

# --------------------------------------------------------------------------
# 1. 找到可用的 Python 3
# --------------------------------------------------------------------------
Say "正在查找 Python 3 ……"
$python = $null
$candidates = New-Object System.Collections.Generic.List[string]

if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($ver in @("-3.12", "-3")) {
        try {
            $out = & py $ver -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $out) {
                $candidates.Add(([string]$out).Trim())
                break
            }
        } catch { }
    }
}
if (Get-Command python -ErrorAction SilentlyContinue) {
    $candidates.Add((Get-Command python).Source)
}
$localPrograms = Join-Path $env:LOCALAPPDATA "Programs\Python"
if (Test-Path $localPrograms) {
    Get-ChildItem -Path $localPrograms -Directory -Filter "Python3*" -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        ForEach-Object {
            $exe = Join-Path $_.FullName "python.exe"
            if (Test-Path $exe) { $candidates.Add($exe) }
        }
}

foreach ($candidate in $candidates) {
    if (-not $candidate) { continue }
    $candidate = ([string]$candidate).Trim()
    if ($candidate -match "WindowsApps") { continue }
    if (-not (Test-Path $candidate)) { continue }
    & $candidate -c "import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) {
        $python = $candidate
        break
    }
}

if (-not $python) {
    Say "没有找到可用的 Python 3。请先安装 python.org 的 Python 3（安装时勾选 Add to PATH）。" "Red"
    exit 1
}
Say "使用 Python：$python" "Green"

$pythonw = Join-Path (Split-Path -Parent $python) "pythonw.exe"
if (-not (Test-Path $pythonw)) { $pythonw = $python }

$stepsPath = Join-Path $AppDir "steps.json"
if (-not (Test-Path $stepsPath)) {
    Say ""
    Say "提醒：还没有 steps.json，任务会按时启动但不知道该点什么。" "Yellow"
    Say "      请先双击 record.bat 录制一遍签到流程，再回来安装任务。" "Yellow"
    Say ""
}

# --------------------------------------------------------------------------
# 2. 自检（用计划任务在真实用户会话里跑，验证能否模拟鼠标键盘）
# --------------------------------------------------------------------------
if ($SelfTest) {
    Say ""
    Say "=== 环境自检：通过计划任务运行 ===" "Cyan"
    $outFile = Join-Path $AppDir "logs\selftest-out.txt"
    New-Item -ItemType Directory -Force -Path (Join-Path $AppDir "logs") | Out-Null
    if (Test-Path $outFile) { Remove-Item $outFile -Force }

    $tempName = "WananChengdianSelftest"
    $arguments = '/c ""{0}" "{1}" selftest > "{2}" 2>&1"' -f $python, $ScriptPath, $outFile
    $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $arguments -WorkingDirectory $AppDir
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $tempName -Action $action -Principal $principal -Force | Out-Null
    try {
        Start-ScheduledTask -TaskName $tempName
        $deadline = (Get-Date).AddSeconds(120)
        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 500
            if (Test-Path $outFile) {
                $content = Get-Content $outFile -Raw -ErrorAction SilentlyContinue
                if ($content -and ($content -match "自检结果")) { break }
            }
        }
        if (Test-Path $outFile) {
            Say ""
            Get-Content $outFile -Encoding UTF8 | ForEach-Object { Say $_ }
        } else {
            Say "自检没有产生输出，请查看 任务计划程序 里 $tempName 的运行结果。" "Red"
        }
    } finally {
        Unregister-ScheduledTask -TaskName $tempName -Confirm:$false -ErrorAction SilentlyContinue
    }
    Say ""
}

if ($SelfTest -and -not $Install) {
    Say "仅做环境自检（未安装任务）。要安装任务请运行 install_task.bat。" "Cyan"
    exit 0
}

# --------------------------------------------------------------------------
# 3. 注册每日任务（默认 22:00 和 23:25 各一次）
# --------------------------------------------------------------------------
Say "正在注册计划任务：$TaskName（每天 $Time 和 $Time2 各一次）……"

$action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$ScriptPath`" run" -WorkingDirectory $AppDir

$triggers = @()
$timeLabels = @()
foreach ($slot in @($Time, $Time2)) {
    if (-not $slot) { continue }
    try {
        $parsed = [datetime]::ParseExact($slot, "HH:mm", $null)
    } catch {
        Say "时间格式不对：$slot（应该是 HH:mm，比如 22:00）" "Red"
        exit 1
    }
    $label = $parsed.ToString("HH:mm")
    $triggers += New-ScheduledTaskTrigger -Daily -At $label
    $timeLabels += $label
}
if ($triggers.Count -eq 0) {
    Say "没有可用的运行时间。" "Red"
    exit 1
}

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$description = "每天 $($timeLabels -join ' 和 ') 各尝试一次：打开微信小程序「成电智慧学工 - 晚安成电」并打卡，成功一次后当天不再重复"

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers `
    -Settings $settings -Principal $principal -Description $description -Force | Out-Null

$info = Get-ScheduledTaskInfo -TaskName $TaskName
$times = $timeLabels -join "、"
Say ""
Say "已安装。" "Green"
Say "  任务名称 : $TaskName"
Say "  尝试时间 : 每天 $times"
Say "  下次运行 : $($info.NextRunTime)"
Say "  运行程序 : $pythonw"
Say "  工作目录 : $AppDir"
Say ""
Say "说明：" "Cyan"
Say "  * 每天尝试 $($triggers.Count) 次：第一次失败会发邮件提醒，第二次是兜底；成功就写进 state.json，当天不再重复。"
Say "  * 任务只在「你已登录且屏幕未锁定」时才有用；锁屏时 Windows 不允许模拟点击。"
Say "  * 电脑需要保持开机（任务已设置唤醒计时器，睡眠可以被唤醒）。"
Say "  * 想临时手动跑一次：双击 run_now.bat（加 --force 可忽略当天已成功的记录）。"
Say "  * 想改时间：install_task.bat -Time 21:50 -Time2 23:20。"

if ($RunNow) {
    Say ""
    Say "立即运行一次 ……" "Cyan"
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 3
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    Say "  最近运行时间：$($info.LastRunTime)  结果代码：$($info.LastTaskResult)"
    Say "  详细日志在：$AppDir\logs\run-*.log"
}
