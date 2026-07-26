# Stock Pulse - 로컬 개발 서버 실행 + 브라우저 자동 열기
# start-web.bat 이 이 스크립트를 호출합니다.

try {
    chcp 65001 > $null
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$web  = Join-Path $root 'web'
$port = 5173
$url  = "http://localhost:$port"

function Test-PortOpen {
    param([int]$Port)
    try {
        (New-Object Net.Sockets.TcpClient('127.0.0.1', $Port)).Close()
        return $true
    } catch {
        return $false
    }
}

function Wait-AndExit {
    param([int]$Code)
    Write-Host ''
    Write-Host '엔터를 누르면 창이 닫힙니다.' -ForegroundColor DarkGray
    [void](Read-Host)
    exit $Code
}

Write-Host '=========================================='
Write-Host '  Stock Pulse - 로컬 서버 실행'
Write-Host '=========================================='
Write-Host ''

# --- Node.js 확인 ---
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host '[X] Node.js 를 찾을 수 없습니다.' -ForegroundColor Red
    Write-Host '    https://nodejs.org 에서 LTS 설치 후 다시 실행하세요.'
    Wait-AndExit 1
}

# --- 이미 켜져 있으면 브라우저만 열고 종료 ---
if (Test-PortOpen $port) {
    Write-Host "[i] 이미 $port 포트에서 서버가 돌고 있습니다. 브라우저만 엽니다." -ForegroundColor Yellow
    Start-Process $url
    Start-Sleep -Seconds 1
    exit 0
}

if (-not (Test-Path (Join-Path $web 'package.json'))) {
    Write-Host "[X] web 폴더를 찾을 수 없습니다: $web" -ForegroundColor Red
    Wait-AndExit 1
}
Set-Location $web

# --- 의존성 설치 ---
if (-not (Test-Path (Join-Path $web 'node_modules\vite'))) {
    Write-Host '[1/2] 의존성 설치 중 ... npm install'
    & npm install
    if ($LASTEXITCODE -ne 0) {
        Write-Host '[X] npm install 실패' -ForegroundColor Red
        Wait-AndExit 1
    }
} else {
    Write-Host '[1/2] 의존성 확인 완료' -ForegroundColor Green
}

# --- 서버가 뜨는 즉시 브라우저 자동 실행 (백그라운드 감시, 최대 60초) ---
$watcher = "for(`$i=0;`$i -lt 120;`$i++){try{(New-Object Net.Sockets.TcpClient('127.0.0.1',$port)).Close();Start-Sleep -Milliseconds 400;Start-Process '$url';break}catch{Start-Sleep -Milliseconds 500}}"
Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $watcher | Out-Null

Write-Host '[2/2] dev 서버 시작 ... (data/ 를 web/public/data 로 자동 복사)' -ForegroundColor Green
Write-Host ''
Write-Host "     주소 : $url" -ForegroundColor Cyan
Write-Host '     종료 : 이 창에서 Ctrl+C, 또는 창 닫기'
Write-Host ''

& npm run dev

Write-Host ''
Write-Host '[i] 서버가 종료되었습니다.'
Wait-AndExit 0
