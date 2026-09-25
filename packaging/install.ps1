# ============================================================
#  知识管理工作台 (KB Workbench) · 一键离线安装 (Windows)
#
#  由 install.bat 调用，也可在 PowerShell 里直接跑：
#    powershell -ExecutionPolicy Bypass -File .\install.ps1
#
#  前置要求：已安装并启动 Docker Desktop（含 compose v2）。
#            本包不含 Docker 本体，只含应用镜像与运行文件。
# ============================================================
#Requires -Version 5.1
param(
    [string]$Dir = "",
    [int]$Port = 8082,
    [int]$BackendPort = 8001,
    [string]$Password = "",
    [string]$Instance = "",
    [string]$DataDir = "",
    [switch]$SkipLoad,
    [switch]$NoStart,
    [switch]$Force,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$PkgRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

# ------------------------------------------------------------
# 输出
# ------------------------------------------------------------
function Write-Step($m) { Write-Host ""; Write-Host "> $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "  [OK] $m" -ForegroundColor Green }
function Write-Warn2($m){ Write-Host "  [!]  $m" -ForegroundColor Yellow }
function Write-Note($m) { Write-Host "      $m" -ForegroundColor Gray }
function Die($m) {
    Write-Host ""
    Write-Host "[X] $m" -ForegroundColor Red
    Write-Host ""
    exit 1
}

# 写 UTF-8 无 BOM 文本。
# 为什么不用 Set-Content -Encoding UTF8：PowerShell 5.1 会写入 BOM，
# 而 docker compose 读 .env 时会把 BOM 当成第一个键名的一部分，
# 结果 KB_ADMIN_PASSWORD 这一项静默失效 —— 表现为「设了口令却登不进去」。
function Write-TextNoBom($Path, $Text) {
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $enc)
}

function New-RandomPassword {
    param([int]$Length = 20)
    $chars = 'abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'.ToCharArray()
    $bytes = New-Object 'System.Byte[]' $Length
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $sb = New-Object System.Text.StringBuilder
    for ($i = 0; $i -lt $Length; $i++) {
        [void]$sb.Append($chars[$bytes[$i] % $chars.Length])
    }
    return $sb.ToString()
}

function To-Slash($p) { return ($p -replace '\\', '/') }

# ------------------------------------------------------------
# 1. 环境体检
# ------------------------------------------------------------
Write-Step "环境检测"

$RawArch = $env:PROCESSOR_ARCHITECTURE
if ($env:PROCESSOR_ARCHITEW6432) { $RawArch = $env:PROCESSOR_ARCHITEW6432 }
switch ($RawArch) {
    'AMD64' { $Arch = 'amd64' }
    'ARM64' { $Arch = 'arm64' }
    'x86'   { $Arch = 'amd64' }
    default { Die "无法识别的 CPU 架构: $RawArch" }
}
Write-Ok "系统: Windows ($RawArch -> $Arch)"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Die @"
没有找到 docker 命令。
   请先安装 Docker Desktop 并启动它：
     https://www.docker.com/products/docker-desktop/
   安装时勾选 "Use WSL 2 based engine"，装好后等鲸鱼图标变绿再重试。
"@
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Die @"
Docker 已安装，但守护进程没有运行。
   请启动 Docker Desktop（开始菜单里搜 Docker），
   等右下角鲸鱼图标不再转动、显示 "Engine running" 后重试。
"@
}
$DockerVer = (docker version --format '{{.Server.Version}}' 2>$null)
Write-Ok "Docker: $DockerVer"

docker compose version *> $null
if ($LASTEXITCODE -ne 0) {
    Die "缺少 docker compose v2。Docker Desktop 自带，请确认它已正常启动。"
}
Write-Ok "Compose: OK"

# ------------------------------------------------------------
# 2. 挑选镜像包
# ------------------------------------------------------------
Write-Step "选择镜像包"

$ImgDir = Join-Path $PkgRoot 'images'
if (-not (Test-Path $ImgDir)) { Die "包结构不完整：缺少 images\ 目录（离线包可能没有完整解压）" }

$Archive = Join-Path $ImgDir "kb-workbench-images-$Arch.tar.gz"
if (-not (Test-Path $Archive)) {
    Write-Warn2 "本机是 $Arch 架构，但包里没有对应的镜像文件。"
    Write-Note "包内现有:"
    Get-ChildItem $ImgDir -Filter 'kb-workbench-images-*.tar.gz' | ForEach-Object {
        Write-Note "  - $($_.Name)"
    }
    Die "请使用包含 $Arch 架构的离线包。"
}
$ArchiveSize = '{0:N0} MB' -f ((Get-Item $Archive).Length / 1MB)
Write-Ok "镜像包: $(Split-Path -Leaf $Archive)  ($ArchiveSize)"

# ------------------------------------------------------------
# 3. 安装目录
# ------------------------------------------------------------
Write-Step "准备安装目录"

if ([string]::IsNullOrWhiteSpace($Dir)) { $Dir = Join-Path $HOME 'kb-workbench' }
if (-not [System.IO.Path]::IsPathRooted($Dir)) { $Dir = Join-Path (Get-Location).Path $Dir }
if (-not (Test-Path $Dir)) { New-Item -ItemType Directory -Path $Dir -Force | Out-Null }
$Target = (Resolve-Path $Dir).Path

$IsUpgrade = Test-Path (Join-Path $Target '.env')
if ($IsUpgrade) {
    Write-Ok "检测到已有安装 -> 按「升级」处理（保留 .env 与全部数据）"
} else {
    $existing = Get-ChildItem $Target -Force -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -ne '.DS_Store' }
    if ($existing -and (-not $Force)) {
        Die "$Target 不是空目录，且里面没有本系统的配置文件。确认要装到这里请加 -Force。"
    }
    Write-Ok "全新安装 -> $Target"
}

# ------------------------------------------------------------
# 数据位置
#   安装目录 = compose 文件 + 运维脚本，几百 KB，几乎不占空间
#   数据根   = data\ + files\ + backups\，会长大
#   生产环境把小盘给安装目录、大盘给数据根，是最省事的扩容方式。
# ------------------------------------------------------------
function Get-EnvValue([string]$Key) {
    $p = Join-Path $Target '.env'
    if (-not (Test-Path $p)) { return '' }
    $hit = Select-String -Path $p -Pattern "^$Key=" -ErrorAction SilentlyContinue |
           Select-Object -First 1
    if (-not $hit) { return '' }
    return ($hit.Line -replace "^$Key=", '').Trim().Trim('"').Trim("'")
}

function Resolve-EnvPath([string]$Value, [string]$Default) {
    if ([string]::IsNullOrWhiteSpace($Value)) { $Value = $Default }
    $Value = ($Value -replace '/', '\') -replace '^\.\\', ''
    if ([System.IO.Path]::IsPathRooted($Value)) { return $Value }
    return (Join-Path $Target $Value)
}

if ($IsUpgrade) {
    # 升级：以 .env 里已有的路径为准 —— 它才是真正生效的。
    # 数据可能早就搬到别的盘了，这里固定打印 $Target\data 会是假信息。
    $ShowData   = Resolve-EnvPath (Get-EnvValue 'KB_DATA_DIR')           './data'
    $ShowFiles  = Resolve-EnvPath (Get-EnvValue 'KB_FILE_STORE_DIR')     './files'
    $ShowBackup = Resolve-EnvPath (Get-EnvValue 'KB_BACKUP_DIR')         './backups'
    $ShowAlt    = Resolve-EnvPath (Get-EnvValue 'KB_BACKUP_ALT_HOST_DIR') './backups-alt'
    $DataRoot   = $ShowData
    Write-Ok "数据目录: $ShowData"
    Write-Host "    文件原文 $ShowFiles / 备份 $ShowBackup"

    if (-not [string]::IsNullOrWhiteSpace($DataDir)) {
        if (-not [System.IO.Path]::IsPathRooted($DataDir)) { $DataDir = Join-Path (Get-Location).Path $DataDir }
        $want = $DataDir.TrimEnd('\')
        if ($want -ne $ShowData.TrimEnd('\')) {
            Write-Host ""
            Write-Warn2 "升级模式不修改数据目录：.env 里已有路径优先级更高，写了也不会生效"
            Write-Host "    当前: $ShowData"
            Write-Host "    想要: $want"
            Write-Host "    搬迁请用（在 WSL / Git Bash 里执行）:"
            Write-Host "      bash scripts/move-data.sh <新的数据根目录（容器内视角的 Linux 路径）>"
            Write-Host "    Windows 上直接搬目录也可以：停服 -> 移动 data\files\backups ->"
            Write-Host "    改 .env 里那四个路径 -> docker compose up -d"
            Write-Host ""
        }
    }
} else {
    if ([string]::IsNullOrWhiteSpace($DataDir)) {
        $DataRoot = $Target
    } else {
        if (-not [System.IO.Path]::IsPathRooted($DataDir)) { $DataDir = Join-Path (Get-Location).Path $DataDir }
        if (-not (Test-Path $DataDir)) { New-Item -ItemType Directory -Path $DataDir -Force | Out-Null }
        $DataRoot = (Resolve-Path $DataDir).Path
    }
    $ShowData   = Join-Path $DataRoot 'data'
    $ShowFiles  = Join-Path $DataRoot 'files'
    $ShowBackup = Join-Path $DataRoot 'backups'
    $ShowAlt    = Join-Path $DataRoot 'backups-alt'
    Write-Ok "数据目录: $ShowData"
    Write-Host "    文件原文 $ShowFiles / 备份 $ShowBackup"
}

if ($DryRun) {
    Write-Host ""
    Write-Host "体检通过（-DryRun，未做任何改动）" -ForegroundColor Green
    Write-Host "  将要执行: 释放 app\ -> $Target，导入 $Arch 镜像，启动服务"
    Write-Host ""
    exit 0
}

# ------------------------------------------------------------
# 4. 释放运行文件
# ------------------------------------------------------------
Write-Step "释放运行文件"

$AppSrc = Join-Path $PkgRoot 'app'
if (-not (Test-Path $AppSrc)) { Die "包结构不完整：缺少 app\ 目录" }
Copy-Item (Join-Path $AppSrc '*') $Target -Recurse -Force

$ScriptsSrc = Join-Path $PkgRoot 'scripts'
if (Test-Path $ScriptsSrc) {
    $scriptsDst = Join-Path $Target 'scripts'
    if (-not (Test-Path $scriptsDst)) { New-Item -ItemType Directory -Path $scriptsDst -Force | Out-Null }
    Copy-Item (Join-Path $ScriptsSrc '*') $scriptsDst -Recurse -Force
}
Write-Ok "运行文件已就位"

# 用上面解析出的真实路径（升级模式下它们来自 .env，可能不在安装目录里），
# 只在缺失处补目录，绝不覆盖已有内容。
foreach ($p in @($ShowData, $ShowFiles, $ShowBackup, $ShowAlt)) {
    if (-not (Test-Path $p)) { New-Item -ItemType Directory -Path $p -Force | Out-Null }
}
Write-Ok "数据目录已就绪"

# ------------------------------------------------------------
# 5. 生成 .env（仅全新安装）
# ------------------------------------------------------------
Write-Step "配置"

# 实例后缀：默认空 = 单机一套（容器名 kb-backend / kb-frontend）。
# 指定后容器名与 compose 项目名都带后缀，可与已有实例并存互不干扰。
#
# 升级时必须沿用 .env 里记着的实例标识：否则 compose 会拿这次的默认值去操作，
# -p kb-workbench 和原来的 -p kb-workbench-qa 是两个不同的项目，轻则认不出
# 原有容器，重则因容器名冲突起不来。
if ($IsUpgrade -and [string]::IsNullOrWhiteSpace($Instance)) {
    $ComposeProject = Get-EnvValue 'COMPOSE_PROJECT_NAME'
    $CBackend       = Get-EnvValue 'KB_BACKEND_CONTAINER'
    $CFrontend      = Get-EnvValue 'KB_FRONTEND_CONTAINER'
    if ([string]::IsNullOrWhiteSpace($ComposeProject)) { $ComposeProject = 'kb-workbench' }
    if ([string]::IsNullOrWhiteSpace($CBackend))       { $CBackend = 'kb-backend' }
    if ([string]::IsNullOrWhiteSpace($CFrontend))      { $CFrontend = 'kb-frontend' }
    Write-Ok "沿用原实例标识: $ComposeProject（容器 $CBackend / $CFrontend）"
} elseif ($Instance) {
    $ComposeProject = "kb-workbench-$Instance"
    $CBackend  = "kb-$Instance-backend"
    $CFrontend = "kb-$Instance-frontend"
    Write-Ok "实例标识: $Instance（容器 $CBackend / $CFrontend）"
} else {
    $ComposeProject = "kb-workbench"
    $CBackend  = "kb-backend"
    $CFrontend = "kb-frontend"
}

$EnvFile = Join-Path $Target '.env'
$AdminPassword = ''

if (-not $IsUpgrade -and [string]::IsNullOrWhiteSpace($Password)) {
    $AdminPassword = New-RandomPassword -Length 20
} elseif (-not $IsUpgrade) {
    $AdminPassword = $Password
}

if (-not (Test-Path $EnvFile)) {
    $dataDirC   = To-Slash (Join-Path $DataRoot 'data')
    $filesDir   = To-Slash (Join-Path $DataRoot 'files')
    $backupDir  = To-Slash (Join-Path $DataRoot 'backups')
    $backupAlt  = To-Slash (Join-Path $DataRoot 'backups-alt')

    $envContent = @"
# ============================================================
# kb-workbench 运行配置（安装脚本自动生成）
# 完整的可调项与说明见同目录 .env.example
# ============================================================

# 初始管理员口令：只在「库里一个用户都没有」时生效，登录后强制改密。
KB_ADMIN_PASSWORD=$AdminPassword

# ---- 端口 ----
KB_FRONTEND_PORT=$Port
KB_BACKEND_PORT=$BackendPort

# ---- 容器名与项目名（同机并存多套实例时靠它们隔离）----
COMPOSE_PROJECT_NAME=$ComposeProject
KB_BACKEND_CONTAINER=$CBackend
KB_FRONTEND_CONTAINER=$CFrontend

# ---- 存储 ----
# 下面四项都是**宿主机路径**，compose 用它们做 bind mount。
# 安装目录只放编排文件（几百 KB），数据全在这四个目录里。
KB_FILE_STORE=fs
KB_DATA_DIR=$dataDirC
KB_FILE_STORE_DIR=$filesDir
KB_BACKUP_DIR=$backupDir
# 第二块盘的挂载位：挂上别的盘后可在「系统设置 -> 备份目录」里一键切换
KB_BACKUP_ALT_HOST_DIR=$backupAlt
BACKUP_SEPARATE_MOUNTS=/mnt/kb-backup
KB_BACKUP_KEEP=14

# ---- 容量 ----
UPLOAD_MAX_MB=1024
LARGE_FILE_WARN_MB=200

# ---- SQLite 调优 ----
SQLITE_CACHE_MB=64
SQLITE_MMAP_MB=256

# ---- 安全 ----
KB_AUTH_ENABLED=true
KB_SESSION_DAYS=14
KB_COOKIE_SECURE=false
KB_MAINTENANCE_ENABLED=true
LOG_LEVEL=INFO
"@
    Write-TextNoBom $EnvFile $envContent
    Write-Ok ".env 已生成（管理员口令：$AdminPassword）"
}

# ------------------------------------------------------------
# 6. 导入镜像
# ------------------------------------------------------------
if ($SkipLoad) {
    Write-Step "跳过镜像导入（-SkipLoad）"
} else {
    Write-Step "导入镜像（$Arch，约 $ArchiveSize，需要一两分钟）"
    docker load -i $Archive
    if ($LASTEXITCODE -ne 0) { Die "镜像导入失败" }
    Write-Ok "镜像已导入"
}

# 把「架构标签」提升为 compose 使用的 :latest。
# 同一台机器若先后导入过两个架构的包，latest 会被覆盖成错的架构，
# 这里按当前架构重新打标签，保证指向正确的那一个。
docker tag "kb-workbench-backend:$Arch"  "kb-workbench-backend:latest"
docker tag "kb-workbench-frontend:$Arch" "kb-workbench-frontend:latest"
Write-Ok "镜像标签已指向本机架构（$Arch）"

# ------------------------------------------------------------
# 7. 启动
# ------------------------------------------------------------
if ($NoStart) {
    Write-Step "跳过启动（-NoStart）"
} else {
    Write-Step "启动服务"
    Push-Location $Target
    try {
        # 先单独校验编排文件：把「配置不合法」和「容器起不来」分开报。
        docker compose -p $ComposeProject config --quiet 2>$null
        if ($LASTEXITCODE -ne 0) {
            Die "docker-compose.yml 配置校验未通过（多半是 Compose 版本过老，
   不认识文件里的新写法）。请手动执行 `docker compose config` 看详细原因。"
        }
        docker compose -p $ComposeProject up -d
        if ($LASTEXITCODE -ne 0) { Die "启动失败，请查看上面的输出" }
    } finally {
        Pop-Location
    }
    Write-Ok "容器已拉起"
}

# ------------------------------------------------------------
# 8. 等待就绪
# ------------------------------------------------------------
if (-not $NoStart) {
    Write-Step "等待服务就绪"
    $ready = $false
    for ($i = 1; $i -le 60; $i++) {
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/healthz" -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -eq 200) { $ready = $true; break }
        } catch { }
        Write-Host "`r      等待中… $($i * 2)s" -NoNewline
        Start-Sleep -Seconds 2
    }
    Write-Host "`r                          `r" -NoNewline
    if ($ready) {
        Write-Ok "服务已就绪"
    } else {
        Write-Warn2 "等待超时（服务可能仍在初始化，或端口被占用）"
        Write-Note "看日志: cd $Target; docker compose logs -f"
    }
}

# ------------------------------------------------------------
# 9. 交付信息
# ------------------------------------------------------------
if ((-not $IsUpgrade) -and $AdminPassword) {
    $pwFile = Join-Path $Target '初始口令.txt'
    Write-TextNoBom $pwFile @"
知识管理工作台 · 初始登录信息
====================================

  地址: http://localhost:$Port
  账号: admin
  口令: $AdminPassword

首次登录会被要求修改口令。
改完之后请删除本文件。
"@
}

Write-Host ""
Write-Host "==============================================" -ForegroundColor Green
Write-Host "  [OK]  知识管理工作台 安装完成" -ForegroundColor Green
Write-Host "==============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  前端访问   http://localhost:$Port" -ForegroundColor White
Write-Host "  后端 API   http://localhost:$BackendPort/api/docs"
Write-Host "  安装目录   $Target"
Write-Host "  数据目录   $ShowData"
Write-Note "（安装目录只放编排文件，数据都在上面这个目录里）"
if ((-not $IsUpgrade) -and $AdminPassword) {
    Write-Host "  登录账号   admin / $AdminPassword" -ForegroundColor Yellow
    Write-Host "             （也记在 $Target\初始口令.txt）"
} else {
    Write-Host "  登录账号   admin（沿用原有口令）"
}
Write-Host ""
Write-Host "  常用操作:"
Write-Host "    启动/停止   cd $Target; docker compose up -d / down"
Write-Host "    看日志      cd $Target; docker compose logs -f"
Write-Host "    数据备份建议指向另一块物理盘（系统设置 -> 备份目录）"
Write-Host ""
