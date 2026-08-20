#Requires -Version 5.1
<#
.SYNOPSIS
  data/ 커밋이 쌓아 올린 git 히스토리를 접는다.

.DESCRIPTION
  파이프라인이 몇 시간마다 data/*.json 을 통째로 다시 커밋한다. 종목이 895개라
  커밋 하나가 수백 개 blob 을 새로 만들고, 그게 그대로 저장소 크기가 된다.
  실측(2026-08-20): 전체 커밋 517개 중 454개(88%)가 chore(data)/chore(brief) 이고
  size-pack 이 79MB 였다. 현재 스냅샷은 34MB 뿐이다 — 나머지는 과거 스냅샷이다.

  과거 데이터 스냅샷은 되돌아볼 가치가 없다 (브리핑은 BRIEF_KEEP_DAYS 로 이미
  정리되고, 종목 JSON 은 매 sync 마다 새로 만들어진다). 그래서 기준 시점보다
  오래된 커밋을 스냅샷 하나로 접는다. 코드 히스토리도 같이 접히므로 잘라낼
  시점은 넉넉히 잡는 게 좋다.

  ⚠️ **히스토리를 다시 쓴다.** 기준 시점 이후 모든 커밋의 SHA 가 바뀌고
  force push 가 필요하다. 다른 클론은 재클론해야 한다. 혼자 쓰는 저장소가
  아니면 하지 말 것. 기본은 미리보기(-Apply 없이는 아무것도 안 바꾼다).

.PARAMETER KeepDays
  최근 며칠치 커밋을 그대로 둘지. 기본 30일.

.PARAMETER Apply
  실제로 히스토리를 고친다. 없으면 계산만 하고 끝난다.

.PARAMETER Push
  -Apply 와 함께 쓰면 origin 에 force push 까지 한다 (--force-with-lease).

.EXAMPLE
  .\squash-data-history.ps1
  얼마나 줄어드는지만 본다.

.EXAMPLE
  .\squash-data-history.ps1 -KeepDays 30 -Apply
  로컬에서만 접는다. 결과를 확인한 뒤 직접 push 한다.
#>
[CmdletBinding()]
param(
  [int]$KeepDays = 30,
  [switch]$Apply,
  [switch]$Push
)

$ErrorActionPreference = 'Stop'

function Show($msg, $color = 'Gray') { Write-Host $msg -ForegroundColor $color }

# PowerShell 은 함수명을 대소문자 없이 찾는다. 함수 이름이 Git 이면 그 안에서
# 부르는 git 이 자기 자신으로 잡혀 무한 재귀가 된다 (call depth overflow).
# 실행 파일 경로를 미리 잡아 두고 그것만 부른다.
$script:GitExe = (Get-Command git.exe -CommandType Application | Select-Object -First 1).Source
function Git { & $script:GitExe @args }

Set-Location $PSScriptRoot

# --- 안전 점검 -------------------------------------------------------------
$dirty = Git status --porcelain
if ($dirty) {
  Show '작업 트리가 깨끗하지 않습니다. 커밋하거나 stash 한 뒤 다시 실행하세요.' Red
  $dirty | Select-Object -First 10 | ForEach-Object { Show "   $_" DarkGray }
  exit 1
}

$branch = (Git rev-parse --abbrev-ref HEAD).Trim()
if ($branch -ne 'main') {
  Show "main 에서만 실행합니다 (현재: $branch)." Red
  exit 1
}

# --- 잘라낼 지점 찾기 ------------------------------------------------------
$cutoff = (Get-Date).AddDays(-$KeepDays).ToString('yyyy-MM-dd')
# 저장소가 KeepDays 보다 어리면 rev-list 가 빈 값을 준다. 파이프 결과가 $null 일
# 때 .Trim() 을 부르면 터지므로 문자열로 먼저 받는다.
$cut = "$(Git rev-list -1 --before=$cutoff HEAD)".Trim()
if (-not $cut) {
  # `log --reverse -1` 은 -1 이 먼저 걸려서 최신 커밋을 준다. 루트를 직접 찾는다.
  $root = "$(Git rev-list --max-parents=0 HEAD)".Trim()
  $first = "$(Git show -s --format=%ci $root)".Trim()
  Show "$cutoff 이전 커밋이 없습니다 — 접을 게 없습니다." Yellow
  Show "   첫 커밋: $first · -KeepDays 를 줄여 보세요." DarkGray
  exit 0
}

$before = [int]((Git count-objects -v | Select-String 'size-pack: (\d+)').Matches[0].Groups[1].Value)
$foldCount = [int]"$(Git rev-list --count $cut)".Trim()
$keepCount = [int]"$(Git rev-list --count "$cut..HEAD")".Trim()

Show ''
Show "기준 시점 : $cutoff (최근 $KeepDays 일 유지)" Cyan
Show "접을 커밋 : $foldCount 개 → 스냅샷 1개" Cyan
Show "유지 커밋 : $keepCount 개" Cyan
Show ("현재 크기 : {0:N0} MB" -f ($before / 1024)) Cyan

if (-not $Apply) {
  Show ''
  Show '미리보기입니다. 실제로 접으려면 -Apply 를 붙이세요.' Yellow
  Show '히스토리를 다시 쓰므로 되돌리기 어렵습니다 — 먼저 백업 클론을 떠 두세요:' DarkGray
  Show '   git clone --mirror . ..\stock-pulse-backup.git' DarkGray
  exit 0
}

# --- 접기 ------------------------------------------------------------------
$backup = "backup/pre-squash-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
Show ''
Show "[1/4] 백업 브랜치 $backup" Cyan
Git branch $backup HEAD

Show '[2/4] 기준 시점 스냅샷 커밋 생성' Cyan
$cutDate = (Git show -s --format=%ci $cut).Trim()
Git checkout --quiet --orphan _squash_tmp $cut
Git commit --quiet -m "chore: 히스토리 압축 — $cutDate 까지의 스냅샷

data/ 를 몇 시간마다 통째로 재커밋하는 구조라 과거 스냅샷이 저장소 대부분을
차지한다. 되돌아볼 가치가 없는 부분이라 커밋 $foldCount 개를 하나로 접었다.
접기 전 상태는 브랜치 $backup 에 남아 있다."
$squashed = (Git rev-parse HEAD).Trim()

Show '[3/4] 최근 커밋을 그 위로 옮기는 중' Cyan
Git checkout --quiet $branch
Git rebase --quiet --onto $squashed $cut $branch
Git branch -D _squash_tmp 2>$null | Out-Null

Show '[4/4] 남은 객체 정리' Cyan
Git reflog expire --expire=now --all
Git gc --prune=now --aggressive --quiet

$after = [int](Git count-objects -v | Select-String 'size-pack: (\d+)').Matches.Groups[1].Value
Show ''
Show ("크기: {0:N0} MB → {1:N0} MB" -f ($before / 1024), ($after / 1024)) Green
Show "백업 브랜치: $backup (확인 뒤 git branch -D $backup)" DarkGray

if ($Push) {
  Show ''
  Show 'origin 에 force push 합니다 (--force-with-lease)' Yellow
  Git push --force-with-lease origin $branch
  Show '완료. 다른 클론이 있다면 재클론해야 합니다.' Yellow
} else {
  Show ''
  Show '로컬만 바뀌었습니다. origin 에 반영하려면:' DarkGray
  Show "   git push --force-with-lease origin $branch" DarkGray
}
