# Stock Pulse - 로컬 개발 서버를 백그라운드로 실행 + 브라우저 자동 열기
# start-web.bat 이 이 스크립트를 호출합니다.

try {
    chcp 65001 > $null
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

$root    = Split-Path -Parent $MyInvocation.MyCommand.Path
$web     = Join-Path $root 'web'
$port    = 5173
$url     = "http://localhost:$port"
$pidFile = Join-Path $root '.dev-server.pid'
$logFile = Join-Path $root '.dev-server.log'

# vite 는 로컬 루프백을 IPv6(::1)에만 바인딩할 때가 있어서 127.0.0.1 소켓 연결로는
# 놓친다. 그래서 리슨 소켓 목록을 직접 본다.
$hasNetTcp = [bool](Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue)

function Test-PortOpen {
    param([int]$Port)
    if ($hasNetTcp) {
        try {
            return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop)
        } catch {
            return $false
        }
    }
    foreach ($addr in @('127.0.0.1', '::1')) {
        $client = New-Object Net.Sockets.TcpClient
        try {
            $async = $client.BeginConnect($addr, $Port, $null, $null)
            if ($async.AsyncWaitHandle.WaitOne(300) -and $client.Connected) { return $true }
        } catch {
        } finally {
            $client.Close()
        }
    }
    return $false
}

function Wait-AndExit {
    param([int]$Code)
    Write-Host ''
    Write-Host '아무 키나 누르면 이 창이 닫힙니다.' -ForegroundColor DarkGray
    try {
        [void][Console]::ReadKey($true)
    } catch {
        [void](Read-Host)
    }
    exit $Code
}

Write-Host '=========================================='
Write-Host '  Stock Pulse - 로컬 서버 실행'
Write-Host '=========================================='
Write-Host ''

# --- 이미 켜져 있으면 알리고 끝 ---
if (Test-PortOpen $port) {
    Write-Host "[i] 서버가 이미 백그라운드에서 실행 중입니다. ($url)" -ForegroundColor Yellow
    Write-Host '    중지하려면 stop-web.bat 을 실행하세요.'
    Wait-AndExit 0
}

# --- Node.js 확인 ---
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host '[X] Node.js 를 찾을 수 없습니다.' -ForegroundColor Red
    Write-Host '    https://nodejs.org 에서 LTS 설치 후 다시 실행하세요.'
    Wait-AndExit 1
}

if (-not (Test-Path (Join-Path $web 'package.json'))) {
    Write-Host "[X] web 폴더를 찾을 수 없습니다: $web" -ForegroundColor Red
    Wait-AndExit 1
}

# --- 의존성 설치 (백그라운드로 넘기기 전에 이 창에서 처리) ---
if (-not (Test-Path (Join-Path $web 'node_modules\vite'))) {
    Write-Host '[1/3] 의존성 설치 중 ... npm install'
    Push-Location $web
    & npm install
    $installCode = $LASTEXITCODE
    Pop-Location
    if ($installCode -ne 0) {
        Write-Host '[X] npm install 실패' -ForegroundColor Red
        Wait-AndExit 1
    }
} else {
    Write-Host '[1/3] 의존성 확인 완료' -ForegroundColor Green
}

# --- dev 서버를 숨김 창으로 띄우고 PID 기록 ---
Write-Host '[2/3] 백그라운드에서 dev 서버 시작 ...' -ForegroundColor Green
$proc = Start-Process -FilePath 'cmd.exe' `
                      -ArgumentList "/c npm run dev -- --port $port --strictPort > `"$logFile`" 2>&1" `
                      -WorkingDirectory $web `
                      -WindowStyle Hidden `
                      -PassThru
Set-Content -Path $pidFile -Value $proc.Id -Encoding ascii

# --- 포트가 열릴 때까지 대기 (최대 60초) ---
$ready = $false
for ($i = 0; $i -lt 120; $i++) {
    if (Test-PortOpen $port) { $ready = $true; break }
    if ($proc.HasExited) { break }
    Start-Sleep -Milliseconds 500
}

if (-not $ready) {
    Write-Host '[X] 서버가 시작되지 않았습니다. 로그 마지막 부분:' -ForegroundColor Red
    if (Test-Path $logFile) {
        Get-Content $logFile -Tail 20 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    }
    Write-Host "    전체 로그: $logFile"
    Wait-AndExit 1
}

Write-Host '[3/3] 준비 완료 - 브라우저를 엽니다.' -ForegroundColor Green
Start-Process $url

Write-Host ''
Write-Host "     주소 : $url" -ForegroundColor Cyan
Write-Host "     로그 : $logFile"
Write-Host '     중지 : stop-web.bat'
Write-Host ''
Write-Host '이 창을 닫아도 서버는 계속 실행됩니다.' -ForegroundColor DarkGray
Wait-AndExit 0
