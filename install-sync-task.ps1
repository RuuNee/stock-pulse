# Stock Pulse - sync-data 를 Windows 예약 작업으로 등록/해제한다.
# install-sync-task.bat 이 이 스크립트를 호출합니다.
#
#   install-sync-task.bat              등록 (기본 시각 07:10 / 17:10)
#   install-sync-task.bat 09:00        등록 (하루 한 번, 지정 시각)
#   install-sync-task.bat remove       해제
#
# 기본 시각을 07:10 / 17:10 으로 잡은 이유:
#   data-sync 봇이 21:30 UTC(06:30 KST) 와 07:30 UTC(16:30 KST) 에 돌고 런당
#   26분쯤 걸린다. 그 직후에 받아야 헛걸음이 없다.

param(
    [string]$At = '',
    [switch]$Remove
)

try {
    chcp 65001 > $null
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

$root     = Split-Path -Parent $MyInvocation.MyCommand.Path
$script   = Join-Path $root 'sync-data.ps1'
$taskName = 'StockPulse-SyncData'

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
Write-Host '  Stock Pulse - 자동 동기화 예약'
Write-Host '=========================================='
Write-Host ''

# `remove` 를 위치 인자로도 받는다 - .bat 이 %1 을 그대로 넘기므로.
if ($At -in @('remove', 'uninstall', 'delete')) { $Remove = $true; $At = '' }

if (-not (Get-Command Register-ScheduledTask -ErrorAction SilentlyContinue)) {
    Write-Host '[X] 이 Windows 에는 ScheduledTasks 모듈이 없습니다.' -ForegroundColor Red
    Wait-AndExit 1
}

# --- 해제 ---
if ($Remove) {
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -eq $existing) {
        Write-Host "[i] 등록된 작업이 없습니다: $taskName" -ForegroundColor Yellow
        Wait-AndExit 0
    }
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "[OK] 예약 작업을 해제했습니다: $taskName" -ForegroundColor Green
    Write-Host '     sync-data.bat 수동 실행은 그대로 됩니다.' -ForegroundColor DarkGray
    Wait-AndExit 0
}

if (-not (Test-Path $script)) {
    Write-Host "[X] sync-data.ps1 을 찾을 수 없습니다: $script" -ForegroundColor Red
    Wait-AndExit 1
}

# --- 트리거 시각 ---
$times = @()
if ($At -eq '') {
    $times = @('07:10', '17:10')
} else {
    $parsed = [datetime]::MinValue
    if (-not [datetime]::TryParseExact($At, 'HH:mm', $null, 'None', [ref]$parsed)) {
        Write-Host "[X] 시각 형식이 잘못됐습니다: '$At' (예: 09:00)" -ForegroundColor Red
        Wait-AndExit 1
    }
    $times = @($At)
}

$triggers = @()
foreach ($t in $times) {
    $triggers += New-ScheduledTaskTrigger -Daily -At $t
}

# -WindowStyle Hidden 만으로는 powershell.exe 가 창을 잠깐 깜빡인다. 작업
# 설정의 -Hidden 과 같이 써야 조용히 돈다.
$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`" -Quiet" `
    -WorkingDirectory $root

# StartWhenAvailable: PC 가 꺼져 있어 시각을 놓쳤으면 켜진 뒤에 따라잡는다.
#   (이게 없으면 노트북은 사실상 주말마다 건너뛴다)
# 배터리 옵션 2개: 노트북이 전원에 안 꽂혀 있어도 돌게 한다.
# ExecutionTimeLimit: 네트워크가 멈춰도 30분이면 접는다. 안 걸어 두면 멈춘
#   인스턴스가 남아 다음 실행을 막는다.
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew `
    -Hidden

# Interactive = 로그온해 있을 때만 실행. 비밀번호를 저장하지 않아도 되고
# 관리자 권한도 필요 없다. git 자격 증명도 사용자 것을 그대로 쓴다.
$principal = New-ScheduledTaskPrincipal `
    -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

try {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $triggers `
        -Settings $settings `
        -Principal $principal `
        -Description 'Stock Pulse: 로컬 data/ 산출물을 정리하고 origin 최신본을 받는다.' `
        -Force | Out-Null
} catch {
    Write-Host '[X] 예약 작업 등록 실패' -ForegroundColor Red
    Write-Host "    $($_.Exception.Message)" -ForegroundColor DarkGray
    Wait-AndExit 1
}

Write-Host "[OK] 등록 완료: $taskName" -ForegroundColor Green
Write-Host "     실행 시각 : $($times -join ' , ') (매일)"
Write-Host "     로그      : $(Join-Path $root '.sync-data.log')"
Write-Host '     창은 뜨지 않습니다. 로그온해 있을 때만 실행됩니다.' -ForegroundColor DarkGray
Write-Host ''
Write-Host '     지금 한 번 돌려보기 : schtasks /run /tn StockPulse-SyncData'
Write-Host '     상태 확인           : schtasks /query /tn StockPulse-SyncData'
Write-Host '     해제                : install-sync-task.bat remove'
Wait-AndExit 0
