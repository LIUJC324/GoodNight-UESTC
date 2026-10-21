param([string]$Message = "chore: 同步本地更新")

# 把本地 wanan-sign 目录同步到 GitHub 仓库（克隆 → 复制 → 提交 → 推送）
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$repo = "https://github.com/LIUJC324/GoodNight-UESTC"
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("GoodNight-UESTC-" + [guid]::NewGuid().ToString("N").Substring(0, 6))

function Say([string]$text, [string]$color = "Gray") { Write-Host $text -ForegroundColor $color }

Say "1/4 检查能不能连上 GitHub ……"
$ok = Test-NetConnection -ComputerName github.com -Port 443 -InformationLevel Quiet -WarningAction SilentlyContinue
if (-not $ok) {
    Say "连不上 github.com（网络/代理问题）。等网络恢复后再双击这个脚本。" "Red"
    exit 1
}

Say "2/4 克隆仓库 ……"
git clone --depth 1 $repo $tmp 2>&1 | Out-Null
if (-not (Test-Path $tmp)) {
    Say "克隆失败，请检查网络或仓库地址。" "Red"
    exit 1
}

try {
    Say "3/4 复制本地文件 ……"
    $files = @("README.md", "LICENSE", ".gitignore", "wechat_auto.py", "settings_gui.pyw",
               "ocr.ps1", "install_task.ps1", "config.example.json", "steps.example.json")
    foreach ($f in $files) {
        Copy-Item (Join-Path $root $f) (Join-Path $tmp $f) -Force
    }
    Copy-Item (Join-Path $root "scripts\*.bat") (Join-Path $tmp "scripts") -Force
    Copy-Item (Join-Path $root "docs\PROGRESS.md") (Join-Path $tmp "docs") -Force
    Copy-Item (Join-Path $root "tools\*.py") (Join-Path $tmp "tools") -Force

    Say "4/4 提交并推送 ……"
    git -C $tmp config user.name "LIUJC324"
    git -C $tmp config user.email "LIUJC324@users.noreply.github.com"
    git -C $tmp add -A
    $status = git -C $tmp status --porcelain
    if (-not $status) {
        Say "本地和仓库一致，没有需要推送的内容。" "Green"
        exit 0
    }
    git -C $tmp commit -m $Message 2>&1 | Out-Null
    git -C $tmp push 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Say "推送失败：可能需要在弹出的窗口里登录 GitHub。" "Red"
        exit 1
    }
    Say "已推送到 https://github.com/LIUJC324/GoodNight-UESTC" "Green"
}
finally {
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue }
}
