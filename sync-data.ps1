# Stock Pulse - 로컬 data/ 를 정리한다.
# sync-data.bat 이 이 스크립트를 호출합니다.
#
# 왜 필요한가:
#   파이프라인을 로컬에서 한 번 돌리면 data/ 아래 tracked JSON 이 190개쯤
#   한꺼번에 바뀐다. 전부 재생성 산출물인데 git 은 "수정됨"으로 잡으니까
#   `git status` 가 못 쓰게 되고, 그 상태로는 pull/rebase 도 막힌다.
#
#   Actions 봇이 하루 12번쯤 같은 파일을 다시 만들어 올리므로, 로컬 산출물은
#   버리고 origin 것을 받는 게 기본이다. 로컬 것을 올려야 할 때만 push 모드.

param([ValidateSet('', 'reset', 'push')][string]$Mode = '')

try {
    chcp 65001 > $null
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if ($Mode -eq '') { $Mode = 'reset' }

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

# 이름이 `Git` 이면 안 된다 — PowerShell 의 명령 해석 순서는 별칭>함수>cmdlet>
# 실행파일이고 이름을 대소문자로 구분하지 않아서, 아래 `& git` 이 git.exe 대신
# 이 함수를 다시 부른다(무한 재귀).
function Invoke-Git {
    # git 은 진행 상황을 stderr 로 쓴다. PowerShell 5.1 에서 그걸 그대로 두면
    # 정상 종료해도 $? 가 false 가 되므로, 판정은 종료 코드로만 한다.
    $out = & git @args 2>&1
    return [pscustomobject]@{ Code = $LASTEXITCODE; Text = ($out -join "`n") }
}

function Show { param([string]$Text, [string]$Color = 'Gray'); Write-Host $Text -ForegroundColor $Color }

Write-Host '=========================================='
Write-Host '  Stock Pulse - 데이터 동기화'
Write-Host '=========================================='
Write-Host ''

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Show '[X] git 을 찾을 수 없습니다.' Red
    Wait-AndExit 1
}

$branch = (Invoke-Git rev-parse --abbrev-ref HEAD).Text.Trim()
if ($branch -ne 'main') {
    Show "[!] 현재 브랜치가 main 이 아닙니다: $branch" Yellow
    Show '    이 스크립트는 main 기준으로 동작합니다.' DarkGray
}

# --- 현재 상태 ---
$dirty = @((Invoke-Git status --porcelain -- data).Text -split "`n" | Where-Object { $_ -ne '' })
Show "[1/4] 로컬 data/ 변경: $($dirty.Count)개 파일"

$fetch = Invoke-Git fetch origin main
if ($fetch.Code -ne 0) {
    Show '[X] fetch 실패 - 네트워크나 인증을 확인하세요.' Red
    Show $fetch.Text DarkGray
    Wait-AndExit 1
}

$counts = (Invoke-Git rev-list --left-right --count 'origin/main...HEAD').Text.Trim() -split '\s+'
$behind = [int]$counts[0]
$ahead  = [int]$counts[1]
Show "      origin 대비: $behind 커밋 뒤짐 / $ahead 커밋 앞섬"

if ($Mode -eq 'push') {
    # ------------------------------------------------------------------
    # push 모드 - 로컬에서 만든 data/ 를 올린다.
    #
    # 봇과 같은 파일을 건드리므로 push 가 거절되는 게 정상이다. 거절되면
    # origin 위로 다시 얹어서 재시도한다 (.github/scripts/commit-data.sh 와
    # 같은 전략). 충돌 시 -X theirs = 지금 올리는 쪽(로컬 재계산분)을 채택한다.
    # ------------------------------------------------------------------
    Show '[2/4] 로컬 데이터를 커밋합니다.' Cyan
    if ($dirty.Count -eq 0) {
        Show '      변경 없음 - 올릴 것이 없습니다.' Yellow
    } else {
        [void](Invoke-Git add data)
        $staged = Invoke-Git diff --cached --quiet
        if ($staged.Code -eq 0) {
            Show '      변경 없음 - 올릴 것이 없습니다.' Yellow
        } else {
            $stamp = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm')
            $commit = Invoke-Git commit -m "chore(data): local sync $stamp UTC"
            if ($commit.Code -ne 0) {
                Show '[X] 커밋 실패' Red
                Show $commit.Text DarkGray
                Wait-AndExit 1
            }

            Show '[3/4] push 시도 (거절되면 origin 위로 다시 얹습니다) ...' Cyan
            $pushed = $false
            for ($i = 1; $i -le 5; $i++) {
                $push = Invoke-Git push origin HEAD:main
                if ($push.Code -eq 0) {
                    Show "      push 성공 (시도 $i/5)" Green
                    $pushed = $true
                    break
                }
                Show "      거절됨 - 다시 얹는 중 (시도 $i/5)" DarkGray
                [void](Invoke-Git fetch origin main)
                $rebase = Invoke-Git rebase -X theirs FETCH_HEAD
                if ($rebase.Code -ne 0) {
                    [void](Invoke-Git rebase --abort)
                    Start-Sleep -Seconds 5
                }
            }
            if (-not $pushed) {
                Show '[X] 5회 실패 - 데이터가 올라가지 않았습니다.' Red
                Wait-AndExit 1
            }
        }
    }
} else {
    # ------------------------------------------------------------------
    # reset 모드 (기본) - 로컬 산출물을 버리고 봇이 만든 최신본을 받는다.
    # ------------------------------------------------------------------
    Show '[2/4] 로컬 data/ 변경을 버리고 origin 것을 받습니다.' Cyan
    if ($dirty.Count -gt 0) {
        # 되돌릴 수 있게 stash 로 밀어 둔다. 산출물이라 실제로 꺼낼 일은
        # 없지만, 지운 뒤에 "그거 필요했는데" 를 되돌릴 방법은 있어야 한다.
        $stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm')
        [void](Invoke-Git stash push -u -m "sync-data: 로컬 data 산출물 $stamp" -- data)
        Show "      $($dirty.Count)개 파일을 stash 로 보관했습니다 (git stash list 로 확인)" DarkGray
    }

    # data/ 밖에 작업 중인 변경이 있으면 rebase 가 거부한다. 그건 사용자가
    # 쓰고 있는 코드지 재생성 산출물이 아니므로, 건드리지 않고 pull 만 건너뛴다.
    $code = @((Invoke-Git status --porcelain).Text -split "`n" |
              Where-Object { $_ -ne '' -and $_ -notmatch '^..\s+"?data/' })
    if ($code.Count -gt 0) {
        Show "[3/4] pull 생략 - data/ 밖에 작업 중인 변경 $($code.Count)개가 있습니다." Yellow
        Show '      커밋하거나 stash 한 뒤 다시 실행하면 origin 최신본을 받습니다.' DarkGray
    } elseif ($behind -gt 0 -or $ahead -gt 0) {
        Show '[3/4] origin/main 위로 정리 중 ...' Cyan
        $pull = Invoke-Git pull --rebase
        if ($pull.Code -ne 0) {
            Show '[X] rebase 실패 - 수동 확인이 필요합니다.' Red
            Show $pull.Text DarkGray
            Wait-AndExit 1
        }
    } else {
        Show '[3/4] 이미 최신입니다.' Green
    }
}

# --- 저장소 관리 ---
# 이 저장소는 하루 12번쯤 190개 JSON 을 통째로 다시 커밋한다. 그 결과 로컬에
# 팩이 계속 쌓이는데, git 기본값(autoPackLimit 50)은 너무 늦게 반응해서
# .git 이 100MB 를 넘긴 뒤에야 정리된다. 임계값을 낮춰 자주 접게 한다.
[void](Invoke-Git config gc.autoPackLimit 8)
[void](Invoke-Git config gc.auto 500)
Show '[4/4] 저장소 정리 중 ...' Cyan
[void](Invoke-Git gc --auto)

$size = (Get-ChildItem .git -Recurse -Force -ErrorAction SilentlyContinue |
         Measure-Object -Property Length -Sum).Sum
Show ("      .git 크기: {0:N0} MB" -f ($size / 1MB)) DarkGray

Write-Host ''
$left = @((Invoke-Git status --porcelain).Text -split "`n" | Where-Object { $_ -ne '' })
if ($left.Count -eq 0) {
    Show '완료 - 작업 트리가 깨끗합니다.' Green
} else {
    Show "완료 - 남은 변경 $($left.Count)개 (data/ 밖):" Green
    $left | Select-Object -First 20 | ForEach-Object { Show "  $_" DarkGray }
}
Wait-AndExit 0
