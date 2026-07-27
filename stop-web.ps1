# Stock Pulse - 백그라운드로 돌고 있는 dev 서버 중지
# stop-web.bat 이 이 스크립트를 호출합니다.

try {
    chcp 65001 > $null
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

$root    = Split-Path -Parent $MyInvocation.MyCommand.Path
$port    = 5173
$pidFile = Join-Path $root '.dev-server.pid'

# start-web.ps1 과 같은 이유로 소켓 연결 대신 리슨 목록을 본다 (IPv6 전용 바인딩 대응).
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
Write-Host '  Stock Pulse - 서버 중지'
Write-Host '=========================================='
Write-Host ''

if (-not (Test-PortOpen $port)) {
    Write-Host "[i] $port 포트에서 실행 중인 서버가 없습니다." -ForegroundColor Yellow
    if (Test-Path $pidFile) { Remove-Item $pidFile -Force }
    Wait-AndExit 0
}

$targets = @()

# 1) start-web.bat 이 남긴 PID (자식 node 프로세스까지 트리로 종료).
#    PID 는 재사용되므로 cmd/node 인지 확인하고 나서 죽인다.
if (Test-Path $pidFile) {
    $saved = (Get-Content $pidFile -Raw).Trim()
    if ($saved -match '^\d+$') {
        $savedProc = Get-Process -Id ([int]$saved) -ErrorAction SilentlyContinue
        if ($savedProc -and $savedProc.ProcessName -in @('cmd', 'node')) { $targets += [int]$saved }
    }
}

# 2) PID 파일이 없거나 어긋난 경우 대비 — 포트를 잡고 있는 프로세스
try {
    $owners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop |
              Select-Object -ExpandProperty OwningProcess -Unique
    $targets += $owners
} catch { }

$stopped = $false
foreach ($target in ($targets | Select-Object -Unique)) {
    if (-not (Get-Process -Id $target -ErrorAction SilentlyContinue)) { continue }
    & taskkill /PID $target /T /F > $null 2>&1
    if ($LASTEXITCODE -eq 0) { $stopped = $true }
}

if (Test-Path $pidFile) { Remove-Item $pidFile -Force }

if ($stopped) {
    Start-Sleep -Milliseconds 500
    if (Test-PortOpen $port) {
        Write-Host "[!] 종료 신호는 보냈지만 $port 포트가 아직 열려 있습니다." -ForegroundColor Yellow
    } else {
        Write-Host '[OK] 서버를 중지했습니다.' -ForegroundColor Green
    }
} else {
    Write-Host "[X] 종료할 프로세스를 찾지 못했습니다. 작업 관리자에서 node 를 확인하세요." -ForegroundColor Red
    Wait-AndExit 1
}

Wait-AndExit 0
