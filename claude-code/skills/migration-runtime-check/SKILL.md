---
name: migration-runtime-check
description: Angular monorepo 의 1회성 마이그레이션 검수. 빌드 단위 앱의 라우트를 자동 평탄화하고, Playwright + 네트워크 시드로 reachable 라우트를 검증한 뒤, 각 페이지의 view·actions·console·screenshot 을 캡처해 A(master) / B(migration) 두 사이드를 비교한다. 자동 판정 X, triage report 산출.
---

# migration-runtime-check

## 정체성

- **1회성 검수 도구**. CI X, 영구 자산 X.
- 사람이 페이지 안 고름. routing module 파싱 + 네트워크 응답 sniff 로 자동.
- 자동 판정 X — 신호 모아 사람 검토.

## 산출물 위치 (반드시 레포 안)

```
<repo-root>/.claude/migration-runtime-check/
  discover-<app>.json
  run-<n>/
    A/
      stamp.json
      pages/<pageId>/{capture.json,page.png}
    B/
      stamp.json
      pages/<pageId>/{capture.json,page.png}
    report.md
    diff.json   # only when compare.py is run with --write-json
```

`.venv`, `.auth/`, `__pycache__/` 는 스킬 디렉토리 안 (`~/.claude/skills/migration-runtime-check/`) 에 두고 gitignore.

## 사전 점검 (에이전트 책임)

1. `python3 --version` ≥ 3.10
2. `~/.claude/skills/migration-runtime-check/.venv` 존재 — 없으면 `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && playwright install chromium`
3. 대상 레포 `<root>/apps/<app>/` 존재
4. dev 서버 떠있나? `curl -s -o /dev/null -w "%{http_code}" <base>/` 로 ping
5. 로그인 필요 앱이면 `.auth/<app>.json` 존재 확인. 없으면 단계 2 로

## 4-단계 흐름

### 1. Parse (dev 서버 불필요)

```bash
cd ~/.claude/skills/migration-runtime-check && source .venv/bin/activate
python3 -c "
from pathlib import Path
from discover import collect_app_routes
import json
out = {}
for app in ['standalone', 'gate', 'sms', 'libs-app']:
    out[app] = {'count': len(collect_app_routes(Path('<root>'), app))}
print(json.dumps(out, ensure_ascii=False, indent=2))
"
```

라우트 수 보고 에이전트가 **빌드 단위 1개 제안** — 라우트 풍부도·도메인·마이그레이션 영향 기준 한 줄 근거. 유저 선택.

### 2. Auth setup (로그인 필요한 앱만)

```bash
cd ~/.claude/skills/migration-runtime-check && source .venv/bin/activate
# 백그라운드 (nohup 금지, & 만)
python3 auth-setup.py --base <base>/<entry> --out .auth/<app>.json \
  > /tmp/mrc-auth.log 2>&1 &
```

에이전트는 추가 polling 금지. **유저 응답만 대기**.

유저가 "로그인 됐어" 하면:
```bash
touch /tmp/mrc-auth-ready
```
auth-setup 이 storageState 저장 + 자동 종료.

### 3. Discover (dev 서버 + auth)

```bash
python3 -u discover.py --app <app> --root <root> \
  --base <base> --auth .auth/<app>.json --timeout 8000
```

- `-u` 필수 (background 시 stdout buffer 회피)
- 산출: `<root>/.claude/migration-runtime-check/discover-<app>.json`
- stdout: `{outPath, totalParsed, reachableCount, excludedCount}` 한 줄 JSON

### 4. Capture (사이드 한 번에 1개)

```bash
python3 -u capture.py <root>/.claude/migration-runtime-check/discover-<app>.json \
  --side A --base <base> --auth .auth/<app>.json \
  --out <root>/.claude/migration-runtime-check/run-1 --timeout 12000
```

- A 캡처 끝 → 유저: 마이그레이션 브랜치 체크아웃 + dev 재기동
- 같은 명령 `--side B` 로 재실행

### 5. Compare

```bash
python3 -u compare.py <root>/.claude/migration-runtime-check/run-1
# → run-1/report.md   (default)

python3 -u compare.py <root>/.claude/migration-runtime-check/run-1 --write-json
# → run-1/report.md + run-1/diff.json   (debug only)
```

기본 산출물은 `report.md` 하나. `diff.json` 은 디버그용으로 `--write-json` 일 때만.

- 입력: `run-<n>/A/pages/<pageId>/capture.json` + `run-<n>/B/pages/<pageId>/capture.json`
  - compare.py 는 레거시 평탄 layout (`run-<n>/<side>/<pageId>/...`) 도 자동 인식
- pageId 로 join, A-only / B-only / both 3분류

비교 신호 (자동 판정 X, **다른 점만** 나열):

- **Page Capture**
  - `view.title`, `finalUrl` (URL 은 host+path 정규화) 동등 비교
  - `view.components` 맵 added/removed/countΔ
  - `view.classes` 맵 added/removed/countΔ + 프레임워크 prefix (`cdk-`, `ng-`, `mat-mdc-`, `_ngcontent`, `_nghost`) 자동 drop
  - `view.headings` (level, text) set diff
  - `view.texts` 가시 텍스트 set diff
  - whiteScreen 플래그: `len(actions)==0`
- **Actions** — `(role, name, locus)` 키 기준
  - 키 set added/removed
  - matched 키의 state 변화 (state_changed)
  - matched 키의 target 변화 (target_changed)
- **Console / Runtime**
  - `console` type ∈ {error, warning} 의 text 첫 줄 set diff (B 신규만)
  - `pageerror` B 신규
  - `requestfailed` `(host+path, failure)` set diff (query 는 GA nonce 노이즈)
- **UI Changes After Actions** — 현재 capture 가 정적 surface 만 수집하므로 `not collected` 로만 표시. action simulation 은 v0 비목표.

screenshot 은 비교 대상 X (픽셀 비결정성). `page.png` 는 증거로 보존하고 report 의 Page Capture 섹션에 경로만 표시.

### report.md 구조

```
# migration-runtime-check report

## Summary
- total pages compared: N
- pages with differences: K
- A-only pages: x
- B-only pages: y
### Category counts (pages affected)
- Page Capture: a
- Actions: b
- Console / Runtime: c

## <pageId>     # 신호 있는 페이지만
### Page Capture
- screenshot path:
  - A: A/pages/<pageId>/page.png
  - B: B/pages/<pageId>/page.png
- (finalUrl/title/components/classes/headings/texts/whiteScreen — 차이 있을 때만)
### Actions      # 차이 있을 때만 섹션 자체 등장
- ...
### Console / Runtime    # 차이 있을 때만
- ...
### UI Changes After Actions
- not collected (action simulation is out of scope for v0)
```

## 실측 함정

- `nohup` 으로 headed Chromium 띄우면 macOS WindowServer 접근 불가로 창 안 뜸. `nohup` 없이 `&` 만.
- Python 백그라운드 실행은 `-u` 안 주면 stdout buffer 로 JSON 누락. 항상 `python3 -u`.
- Angular dev server 는 `/home` 같은 SPA 라우트에 404 응답 + index.html body. HTTP status 신뢰 X. finalUrl 만 봄.
- `networkidle` wait 는 HMR websocket 때문에 안 떨어짐. `domcontentloaded` + 짧은 추가 sleep.
- 동시에 한 사이드만 캡처. workers=1. 결정성 우선.

## 비목표 (v0)

- 클릭 후 동작 검증 (actions 는 존재·상태만)
- transition 검증
- CI 통합
- 자동 판정
- 라우트 자동 발견 (X — 명시된 routing module 파싱만)

