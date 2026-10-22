<#
  晚安成电 · 签到提醒：每天定时发一封邮件提醒（不操作微信）

  用法：
    powershell -ExecutionPolicy Bypass -File install_remind.ps1
    powershell -ExecutionPolicy Bypass -File install_remind.ps1 -Time1 21:30 -Time2 23:00
    powershell -ExecutionPolicy Bypass -File install_remind.ps1 -Remove
#>
[CmdletBinding()]
param(
    [string]$Time1 = "22:00",
    [string]$Time2 = "23:15",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TaskName = "WananChengdianRemind"
$ScriptPath = Join-Path $AppDir "wechat_auto.py"

function Say([string]$Text, [string]$Color = "Gray") {
    Write-Host $Text -ForegroundColor $Color
}

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Say "已删除提醒任务：$TaskName" "Green"
    } else {
        Say "没有找到提醒任务 $TaskName"
    }
    exit 0
}

if (-not (Test-Path $ScriptPath)) {
    Say "找不到 wechat_auto.py，请确认脚本和本文件在同一个文件夹。" "Red"
    exit 1
}

# 找 pythonw.exe（静默运行，不弹黑框）
$pythonw = $null
$candidates = New-Object System.Collections.Generic.List[string]
if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($ver in @("-3.12", "-3")) {
        try {
            $exe = & py $ver -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe) { $candidates.Add($exe) }
        } catch { }
    }
}
if (Get-Command python -ErrorAction SilentlyContinue) { $candidates.Add((Get-Command python).Source) }
foreach ($exe in $candidates) {
    $dir = Split-Path -Parent $exe
    $w = Join-Path $dir "pythonw.exe"
    if (Test-Path $w) { $pythonw = $w; break }
}
if (-not $pythonw) {
    Say "没找到 pythonw.exe，请确认 Python 已安装并加入 PATH。" "Red"
    exit 1
}
Say "使用 Python：$pythonw"

$arguments = "`"$ScriptPath`" remind"
$action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $AppDir

$trigger1 = New-ScheduledTaskTrigger -Daily -At $Time1
$trigger2 = New-ScheduledTaskTrigger -Daily -At $Time2
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -WakeToRun:$false -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($trigger1, $trigger2) `
    -Settings $settings -Principal $principal -Force | Out-Null

Say "已安装提醒任务：$TaskName" "Green"
Say "  每天提醒时间：$Time1、$Time2（北京时间）"
Say "  动作：pythonw wechat_auto.py remind（只发邮件，不动微信）"
Say ""
Say "测试一次：python wechat_auto.py remind" "Gray"
Say "删除：scripts\uninstall_reminder.bat" "Gray"
