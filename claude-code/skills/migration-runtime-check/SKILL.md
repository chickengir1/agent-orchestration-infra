---
name: migration-runtime-check
description: Angular monorepo 의 1회성 마이그레이션 검수. 사람이 승인한 check-plan 의 scenario 단위로 A(baseline) / B(candidate) 두 사이드에서 페이지 진입·view/actions/console/screenshot 을 캡처하고, scenarioId 기준으로 differences-only report 를 생성한다. 자동 판정 X.
---

# migration-runtime-check

## 정체성

- **1회성 검수 도구**. CI X, 영구 자산 X.
- 비교 단위는 route 가 아니라 **scenario** (route + context + concrete path + expectedFinalPath).
- 자동 판정 X — 신호 모아 사람 검토.
- check-plan 이 테스트 요구사항의 source of truth. discover 는 후보 수집만.
- context 의 role/group/permission 은 **opaque label**. 도구는 의미를 추론하지 않음.

## 산출물 위치 (반드시 레포 안)

```
<repo-root>/.claude/migration-runtime-check/
  discover-<app>.json          # discover.py 산출
  check-plan-<app>.json        # 사람이 승인한 plan
  run-<n>/
    A/
      stamp.json
      pages/<scenarioId>/
        capture.json                    # initial capture
        page.png
        actions/<actionId>/step-<N>/
          action.json                   # 실행 결과·status·error
          capture.json                  # step 직후 view/actions/meta (snapshotAfterEachStep=true 일 때)
          page.png
    B/
      stamp.json
      pages/<scenarioId>/...
    report.md
    diff.json                  # compare.py --write-json 일 때만
```

`.venv`, `.auth/`, `__pycache__/` 는 스킬 디렉토리 안 (`~/.claude/skills/migration-runtime-check/`) 에 두고 gitignore.

## 사전 점검 (에이전트 책임)

1. `python3 --version` ≥ 3.10
2. `~/.claude/skills/migration-runtime-check/.venv` 존재 — 없으면 `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && playwright install chromium`
3. 대상 레포 `<root>/apps/<app>/` 존재
4. dev 서버 떠있나? `curl -s -o /dev/null -w "%{http_code}" <base>/` 로 ping
5. 로그인 필요 앱이면 `.auth/<app>.json` 존재 확인

## 12-단계 workflow

브랜치 checkout / auth 는 사람이 직접. 자동화 확장 X.

### 1. Context metadata 설정

사람이 어떤 컨텍스트로 비교할지 결정. role / group / permissionScope / tenant / plan 은 모두 opaque label.

### 2. Claude 가 strict mode 로 필요한 값만 질문

자유 대화 X. 아래 키만 묻는다. 모르면 `unknown` 허용.

- target app (apps/<app>)
- baseline branch
- migration branch
- base URL (dev 서버)
- auth storageState path (또는 null)
- context id
- route variables (예: `group_id=2`)
- human labels (role / group / permissionScope, opaque)
- must-cover domains
- out-of-scope domains
- known unstable surfaces (loading spinner / carousel nonce / timestamp 등)

### 3. 사용자 답변

### 4. Claude 가 context metadata 생성

답변을 그대로 check-plan 의 `contexts[]` 배열로 변환. 의미 추론 없음.

### 5. Claude 가 discover 로 route 후보 수집

```bash
cd ~/.claude/skills/migration-runtime-check && source .venv/bin/activate
python3 -u discover.py --app <app> --root <root> \
  --base <base> --auth .auth/<app>.json --timeout 8000
```

- `-u` 필수
- 산출: `<root>/.claude/migration-runtime-check/discover-<app>.json`
- stdout: `{outPath, totalParsed, reachableCount, excludedCount}` 한 줄 JSON
- 이건 **후보 수집**이지 테스트 정의 아님.

### 6. Claude 가 check-plan 초안 생성

`plan_helper.py` 를 사용하거나 직접 작성.

```bash
python3 plan_helper.py \
  --discover <root>/.claude/migration-runtime-check/discover-<app>.json \
  --app <app> --baseline-branch dev --candidate-branch <migration-branch> \
  --base-url http://localhost:4200 --auth .auth/<app>.json \
  --context-id group-2-admin --vars group_id=2 \
  --labels "유료 학교,설정 가능 계정" \
  --metadata-json '{"접근 대상":"2번 그룹","그룹 내 권한":"관리자"}' \
  --known-unstable "lds-bars,lds-css,ngucarousel,Fetching" \
  > <root>/.claude/migration-runtime-check/check-plan-<app>.json
```

discover 의 `reachable[]` 에서 routeTemplate 을 골라 scenario 후보 배열로. scenarioId 는 `{routeSlug}-{contextId}` 형태로 자동 생성.

### 7. 사용자가 check-plan 승인/수정

- 추가/제거할 scenario
- expectedFinalPath 조정 (권한 가드로 인한 의도된 redirect 처리)
- knownUnstable 패턴 추가
- context 별 vars / labels 보정

승인된 check-plan 이 **테스트 요구사항의 source of truth**.

### 8. A 기준 브랜치에서 capture

사람이 baseline 브랜치 checkout + dev 서버 기동. Claude 가:

```bash
python3 -u capture.py --plan <root>/.claude/migration-runtime-check/check-plan-<app>.json \
  --side A --out <root>/.claude/migration-runtime-check/run-1 --timeout 12000
```

### 9. B 마이그레이션 브랜치에서 capture

사람이 candidate 브랜치 checkout + dev 서버 재기동. 같은 plan 으로 `--side B` 재실행.

### 10. scenarioId 기준 compare

```bash
python3 -u compare.py <root>/.claude/migration-runtime-check/run-1
# → run-1/report.md   (default; plan 은 stamp.json 의 planPath 로 자동 로드)

python3 -u compare.py <root>/.claude/migration-runtime-check/run-1 \
  --plan <root>/.claude/migration-runtime-check/check-plan-<app>.json
# → 명시 plan 사용 (자동 로드보다 우선)

python3 -u compare.py <root>/.claude/migration-runtime-check/run-1 --write-json
# → run-1/report.md + run-1/diff.json   (debug only)
```

- 기본 산출물은 `report.md` 하나
- scenarioId 로 A/B join
- check-plan 의 `knownUnstable` 패턴은 classes / texts / non-error console 신호에만 substring 매칭. 매칭된 신호는 main diff 가 아니라 **Noise Candidates** 섹션으로 분리.
- finalUrl / actions / pageerror / requestfailed / components / headings 는 noise 분류 대상 아님 (항상 main diff).
- check-plan 을 못 찾으면 `knownUnstable=[]` 로 계속 동작하되 report Summary 에 `check-plan not loaded` 표시.
- main diff 가 없고 노이즈만 잡힌 scenario 는 **Differences 섹션에서 제외**되고 별도 `## Noise-only Scenarios` 섹션에 scenarioId + noise 요약으로 표시. Summary 에 `noise-only scenarios` 카운트도 추가.

### 11. differences-only report.md 생성

같은 점은 쓰지 않는다. 신호 없는 scenario 는 통째 생략.

### 12. engineering retrospective 작성

report.md 끝에 빈 retrospective template 만 자동 삽입. 본문은 사람이 채움.

## check-plan schema (요약)

상세 명세는 `check-plan.schema.json`.

```json
{
  "app": "libs-app",
  "intent": "Angular migration runtime parity check",
  "baseline":  { "branch": "dev", "baseUrl": "http://localhost:4200" },
  "candidate": { "branch": "sbe-web-v4-angular-migration", "baseUrl": "http://localhost:4200" },
  "auth": { "storageState": ".auth/libs-app.json", "actor": "default", "role": "unknown" },
  "knownUnstable": ["lds-bars", "lds-css", "ngucarousel", "Fetching"],
  "contexts": [
    {
      "id": "group-2-admin",
      "auth": null,
      "vars": { "group_id": "2" },
      "labels": ["유료 학교", "설정 가능 계정"],
      "metadata": {
        "접근 대상": "2번 그룹",
        "그룹 내 권한": "관리자",
        "검증 의도": "설정 페이지 접근 유지"
      }
    }
  ],
  "scenarios": [
    {
      "id": "settings-facultylist-group-2-admin",
      "reason": "permission-guarded settings page",
      "routeTemplate": "/group/:group_id/settings/facultylist",
      "context": "group-2-admin",
      "path": "/group/2/settings/facultylist",
      "expectedFinalPath": "/group/2/settings/facultylist",
      "compare": ["page-capture", "actions", "console-runtime"],
      "actions": [
        {
          "id": "open-permission-dropdown",
          "kind": "safe-ui-action",
          "description": "권한 드롭다운 펼치기",
          "snapshotAfterEachStep": true,
          "steps": [
            { "type": "click", "selector": "[data-testid='permission-dropdown']" }
          ]
        }
      ]
    }
  ]
}
```

### Approved safe UI action 정책 (v1)

- check-plan 의 `scenarios[].actions[]` 에 명시된 action 만 실행. extract.js 가 발견한 action 을 자동 순회 X.
- v1 지원 step 타입: `click` 만.
- v1 비목표: navigation action, form submit / save / delete / create / update / send / payment 같은 mutating action, action 후보 자동 생성, pixel diff.
- selector 정책: `[data-testid=...]` 우선, `aria-label` / `role`+`name` 가능, **generated class selector 금지**.
- step 의 action.json status 값:
  - `ok` — click 성공, finalPath 변화 없음
  - `selector-not-found` / `selector-ambiguous` — locator count != 1
  - `unsafe-selector` — selector 에 `.ng-` / `.cdk-` / `.mat-mdc-` / `._ngcontent` / `._nghost` 패턴 포함 → click 실행하지 않음
  - `navigation-detected` — click 후 `finalPath` 가 변경됨 → safe-ui-action 범위 이탈 evidence
  - `error` — selector 평가 또는 click 자체에서 예외
  - `skipped` — 같은 action 의 이전 step 이 정상 완료되지 못해 후속 step 실행 안 함
- action 결과는 diff 가 아니라 **evidence**. pass/fail 판정 X.
- 각 step 직후 `snapshotAfterEachStep` (default true) 이면 view/actions/meta + screenshot 저장. `unsafe-selector` step 은 page 상태가 변하지 않으므로 snapshot 생략.

action.json 예시 (ok):

```json
{
  "actionId": "open-permission-dropdown",
  "step": 1,
  "type": "click",
  "selector": "[data-testid='permission-dropdown']",
  "status": "ok",
  "error": null,
  "beforeFinalPath": "/group/2/settings/facultylist",
  "afterFinalPath": "/group/2/settings/facultylist"
}
```

action.json 예시 (failure):

```json
{
  "actionId": "open-permission-dropdown",
  "step": 1,
  "type": "click",
  "selector": "[data-testid='permission-dropdown']",
  "status": "selector-not-found",
  "error": "0 elements matched"
}
```

## 비교 신호

자동 판정 X, **다른 점만** 나열.

### Page Capture

- `finalUrl` (host+path 정규화) 동등 비교
- `view.title` 동등
- `view.components` 맵 added/removed/countΔ
- `view.classes` 맵 added/removed/countΔ + 프레임워크 prefix (`cdk-`, `ng-`, `mat-mdc-`, `_ngcontent`, `_nghost`) 자동 drop
- `view.headings` (level, text) set diff
- `view.texts` 가시 텍스트 set diff
- whiteScreen 플래그: `len(actions)==0`

### Actions

`(role, name, locus)` 키 기준.

- 키 set added / removed
- matched 키의 state 변화 (state_changed)
- matched 키의 target 변화 (target_changed)

### Console / Runtime

- `console` type ∈ {error, warning} 의 text 첫 줄 set diff (B 신규만)
- `pageerror` B 신규
- `requestfailed` `(host+path, failure)` set diff

### Noise Candidates (분리 섹션, main diff 에서 제외)

check-plan 의 `knownUnstable` 패턴이 다음 3축의 신호 항목에 substring 매칭되면 Noise Candidates 로 분류.

- `view.classes` added / removed / changed
- `view.texts` added
- `console` 의 type ∈ {warning, log, info, debug} (즉 **error 아닌 콘솔**)

매칭되지 않는 항목은 main diff 에 그대로 남는다. finalUrl / actions / pageerror / requestfailed / components / headings 는 noise 분류 대상 아님.

### Invalid Captures

scenario 의 `expectedFinalPath` 와 capture 의 `finalPath` 가 다르면 **deep diff 를 건너뛰고** report 의 Invalid Captures 섹션에만 기록한다. 양쪽 사이드 중 하나라도 expectedFinalPath 에 도달하지 못하면 그 scenario 는 invalid 처리.

screenshot 은 비교 대상 X (픽셀 비결정성). `page.png` 는 증거로 보존하고 report 의 Page Capture 섹션에 경로만 표시.

## report.md 구조

```
# Migration Runtime Check Report

## Summary
- total scenarios: N
- scenarios with differences: K
- noise-only scenarios: M
- invalid captures: I
- A-only scenarios: x
- B-only scenarios: y
- (check-plan not loaded — 자동 로드 실패 시에만)
### Category counts (scenarios affected)
- Page Capture: a
- Actions: b
- Console / Runtime: c

## Invalid Captures
### <scenarioId>
- expected: <expectedFinalPath>
- A finalPath: ...
- B finalPath: ...
- reason: <which side mismatched>
- deep diff: skipped

## Differences
### <scenarioId>
Context:
- auth: ...
- vars: ...
- labels: tag1, tag2
- metadata:
  - 접근 대상: "..."
  - 그룹 내 권한: "..."

#### Page Capture
- screenshot:
  - A: A/pages/<scenarioId>/page.png
  - B: B/pages/<scenarioId>/page.png
- (finalUrl / title / components / classes / headings / texts / whiteScreen — 차이 있을 때만)

#### Actions      # 차이 있을 때만 섹션 등장
- ...

#### Console / Runtime    # 차이 있을 때만
- ...

#### UI Changes After Actions    # action 실행 + 결과 차이 있을 때만
##### <actionId> / step-<N>
- action:
  - A: ok
  - B: selector-not-found
- screenshot:
  - A: A/pages/<scenarioId>/actions/<actionId>/step-<N>/page.png
  - B: B/pages/<scenarioId>/actions/<actionId>/step-<N>/page.png
- differences:    # 양쪽 status 가 ok 일 때 step capture diff 요약
  - headings: +1 -1
  - ...

#### Noise Candidates    # 매칭된 항목 있을 때만
- ...

## Noise-only Scenarios    # main diff 0 + 노이즈만 있을 때
- <scenarioId>: classes +N -M ΔK; texts +T; console (non-error) +C

## Engineering Retrospective
(template — 사람이 작성)

### Prediction From Code / Plan
- 어떤 scenario 가 위험하다고 봤는지
- 왜 그 scenario 를 골랐는지
- 어떤 차이를 예상했는지

### Actual Runtime Evidence
- 실제 캡처에서 나온 차이
- invalid capture
- noise
- 진짜 확인 필요한 항목

### Judgment
- 도구가 신뢰 가능하게 동작했는지
- migration 회귀로 단정 가능한 항목이 있는지
- 다음 보강점
```

## 실측 함정

- `nohup` 으로 headed Chromium 띄우면 macOS WindowServer 접근 불가. `nohup` 없이 `&` 만.
- Python 백그라운드는 `-u` 안 주면 stdout buffer 로 JSON 누락. 항상 `python3 -u`.
- Angular dev server 는 `/home` 같은 SPA 라우트에 404 응답 + index.html body. HTTP status 신뢰 X. **finalPath 만 본다.**
- `networkidle` wait 는 HMR websocket 때문에 안 떨어짐. `domcontentloaded` + 짧은 추가 sleep.
- 동시에 한 사이드만 캡처. workers=1. 결정성 우선.

## 비목표

- action 후보 자동 생성 / extract.js actions 자동 순회
- mutating action (form submit, save, delete, create, update, send, payment 등)
- navigation action (v1 범위 외)
- v1 외 step 타입 (현재 `click` 만)
- transition 검증
- CI 통합
- 자동 pass/fail 판정 / 4상태 라벨
- pixel diff / computed style diff
- screenshot diff
- legacy route-based pageId / discover-positional capture (폐기됨)
