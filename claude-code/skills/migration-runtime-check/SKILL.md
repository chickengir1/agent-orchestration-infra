---
name: migration-runtime-check
description: Angular monorepo 의 1회성 마이그레이션 검수. check-plan 의 scenario 단위로 A(baseline) / B(candidate) 두 사이드에서 페이지 진입·action surface·console·user flow evidence·screenshot 을 캡처하고, scenario matrix report 를 생성한다. 자동 판정 X.
---

# migration-runtime-check

## 정체성

- **1회성 검수 도구**. CI X, 영구 자산 X.
- 비교 단위는 route 가 아니라 **scenario** (route + context + concrete path + expectedFinalPath).
- 자동 판정 X — 신호 모아 사람 검토.
- check-plan 이 테스트 요구사항의 source of truth. discover 는 후보 수집만.
- context 의 도메인 속성은 **opaque metadata**. 도구는 의미를 추론하지 않음.

## 산출물 위치 (반드시 레포 안)

```
<repo-root>/.claude/migration-runtime-check/
  discover-<app>.json          # discover.py 산출
  check-plan-<app>.json        # capture 계약
  run-<n>/
    <baselineBranch>/           # slug(baseline.branch), e.g. dev
      stamp.json                # side=A, role=baseline, branch=<baseline.branch>
      retry-candidates.json     # initial side pass 후 retry 대상
      retry-history.json        # retry pass 결과와 덮어쓰기 기록
      <contextId>/
        pages/<scenarioId>/
          capture.json                  # initial capture
          # capture.json.settled: 1초 지연 후 안정 스냅샷(있을 때)
          page.png
          flows/<flowId>/step-<N>/
            step.json                   # 실행 결과·status·error
            capture.json                # step 직후 view/actions/runtime/meta (snapshotAfterEachStep=true 일 때)
            page.png
    <candidateBranch>/          # slug(candidate.branch), e.g. sbe-web-v4-angular-migration
      stamp.json                # side=B, role=candidate, branch=<candidate.branch>
      <contextId>/pages/<scenarioId>/...
    report.md
    diff.json                  # compare.py --write-json 일 때만
```

`.venv`, `.auth/`, `__pycache__/` 는 스킬 디렉토리 안 (`~/.claude/skills/migration-runtime-check/`) 에 두고 gitignore.

`--side A/B` 는 capture 역할 선택자일 뿐 산출물 디렉터리명이 아니다. 실제 디렉터리명은 check-plan 의
`baseline.branch` / `candidate.branch` 를 filesystem-safe slug 로 변환한 값이다. baseline 과 candidate
브랜치명이 같으면 candidate 쪽은 `<branch>-candidate` 로 쓴다.

## 사전 점검 (에이전트 책임)

런타임 환경 점검만 먼저 한다. 앱과 도메인 지식이 확정되기 전에는 dev 서버 / auth 를 확인하지 않는다.

1. `python3 --version` ≥ 3.10
2. `~/.claude/skills/migration-runtime-check/.venv` 존재 — 없으면 `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && playwright install chromium`

대상 레포의 build unit 탐색, dev 서버 ping, `.auth/<app>.json` 존재 확인은 app 과 도메인 메타데이터가 확정된 이후에 수행한다.

## 12-단계 workflow

브랜치 checkout / auth 는 사람이 직접. 자동화 확장 X.

필수 도달 시퀀스는 다음 4단계다. 이 순서를 만족하지 못하면 이 스킬은 폐기한다.

1. 라우트 구조를 1회 수집한다. 브랜치별로 다시 추출하지 않는다.
2. check-plan 으로 baseline(A) 런타임을 수집한다.
3. 같은 check-plan 으로 candidate(B) 런타임을 수집한다.
4. A 대비 B의 이상한 점만 보고한다. 기준은 사용자가 보는 view, action surface, console/runtime, user flow step 이후 화면 변화다.

### 1. 대상 레포의 build unit 조사

`<root>` 의 build unit 을 먼저 조사한다. 예: `apps/*`, Angular workspace project 정의, package script, 로컬 repo 의 기존 앱 구조.

이 단계에서는 dev 서버 / auth 를 확인하지 않는다. 발견한 후보 app 목록을 사용자에게 제시해야 하며, 대화 맥락만 보고 app 을 추정하지 않는다.

### 2. Claude 가 app / branch 만 질문

build unit 후보를 근거로 app 을 묻고, baseline / candidate branch 조합을 묻는다. 모르면 `unknown` 허용.

- target app (발견한 build unit 후보 중 선택)
- baseline branch
- migration branch

`검수 범위`는 이 단계에서 묻지 않는다.

### 3. 사용자 app / branch 답변

### 4. Claude 가 선택지 기반 입력 UX 를 3단계로 분리

app 과 branch 가 정해진 뒤, 아래 순서로만 입력을 받는다. 한 번에 뭉뚱그려 묻지 않는다.

Claude Code 에 선택지 기반 사용자 입력 프롬프트가 있으면 반드시 그걸 쓴다. 자유 텍스트 질문 하나로 대체하지 않는다. 선택지 프롬프트를 쓸 수 없는 환경에서만 번호형 텍스트 질문으로 fallback 한다.

1. **유저 정보**
   - 선택지:
     - 기존 `.auth/<app>.json` 재사용
     - 새 유저/token JSON 입력으로 `.auth/<app>.json` 갱신
     - 비로그인 상태로 진행
   - token JSON 이 들어오면 `.auth/<app>.json` 갱신에만 사용하고 원문은 plan/report/stamp/capture 에 저장하지 않는다.
   - 이 단계의 산출은 `auth.storageState`, `auth.actor`, `auth.role` 같은 실행 주체 정보다.
2. **도메인 지식**
   - 자유 입력으로 받는다. 스킬이 특정 도메인 항목을 템플릿처럼 요구하지 않는다.
   - 사용자가 말한 표본, 식별자, 상태, 분류, 범위, 제외 조건, 기대 이동, 불안정 요소를 그대로 구조화한다.
   - 이 단계의 산출은 입력 내용에 맞춰 생성한 JSON 이다: `contexts[]`, `contexts[].vars`, `contexts[].labels`, `contexts[].metadata`, `knownUnstable`, scenario 후보 선정 근거.
3. **유저 플로우**
   - 사용자가 알고 있는 업무 흐름이나 검증 관심사를 자유 입력으로 받는다.
   - 유저에게 페이지 내부 버튼명, 탭명, 드롭다운명, selector 지식을 요구하지 않는다.
   - 구체 페이지/컨트롤 정보가 없는 경우 Claude 가 discover 결과와 코드/route 이름을 보고 safe-ui-flow 후보를 만들거나 `no flows selected` 로 둔다.
   - 이 단계의 산출은 scenario 별 `flows[]` 또는 명시적 `no flows selected` 기록이다.

사용자가 입력한 도메인 정보는 check-plan 의 `contexts[]`, `knownUnstable`, scenario 후보 선정 근거로 변환한다. 고정 템플릿에 끼워 맞추지 않고, 입력 문장에 실제로 존재하는 개념만 JSON key 로 만든다.

도구는 도메인 용어의 의미를 추론하지 않는다. 사용자가 준 설명을 구조화해서 보존한다.

유저 플로우 입력은 도메인 메타데이터와 섞지 않는다. 사용자가 구체 컨트롤을 모르면 묻지 말고, Claude 가 route/code/action 후보를 보고 scenario 의 `flows[]` 에 명시적으로 매핑하거나, 안전 selector 가 없어 제외했음을 plan 에 남긴다.

유저 정보와 도메인 지식까지 확정된 뒤에야 dev 서버 ping, `.auth/<app>.json` 존재 확인, base URL / auth storageState path 확정을 수행한다.

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
  --context-id <context-id> --vars <key>=<value> \
  --labels "<opaque-label-1>,<opaque-label-2>" \
  --metadata-json '{"사용자가 말한 항목":"사용자가 준 값"}' \
  --known-unstable "<unstable-fragment-1>,<unstable-fragment-2>" \
  > <root>/.claude/migration-runtime-check/check-plan-<app>.json
```

discover 의 `reachable[]` 에서 routeTemplate 을 골라 scenario 후보 배열로. scenarioId 는 `{routeSlug}-{contextId}` 형태로 자동 생성.

#### 6-1. user-flow 후보 처리 (capture 전 필수)

draft 가 만들어진 직후, capture 로 진행하기 전에 flow 후보를 한 번 명시적으로 처리한다.

- 사용자가 도메인 지식 입력에서 flow / 인터랙션 / 클릭 / 드롭다운 등 UI 상호작용을 요청했거나, scenario 의 검증 의도상 안전한 UI 인터랙션이 필요한 경우:
  - 해당 scenario 의 `flows[]` 에 v1 safe-ui-flow (click only, `[data-testid=...]` / `aria-label` / `role`+`name` selector) 항목을 명시적으로 추가한다.
  - 추가할 flow 후보가 없거나 safe selector 가 확인되지 않으면, scenario 의 `reason` 또는 plan 상단 메모에 **"no flows selected"** 문장을 명시적으로 남긴다.
- flow 테스트가 요청됐는데 어떤 scenario 의 `flows[]` 도 비어 있고 "no flows selected" 기록도 없는 상태로는 Step 8 capture 를 시작하지 않는다. (silent flows=0 금지)

### 7. Claude 가 check-plan 저장 후 capture 로 진행

check-plan 은 capture 계약이다. Claude 는 초안을 만든 뒤 장황한 승인 핑퐁으로 멈추지 않는다. 명백한 모순이나 위험한 mutating flow 가 없으면 저장하고 다음 단계로 간다.

- scenario 는 discover 후보와 도메인 지식을 근거로 보수적으로 고른다.
- expectedFinalPath 는 알 수 없으면 route path 와 동일하게 두고, capture retry/invalid 결과에서 보정 후보로 보고한다.
- flow 는 안전 selector 가 확인된 경우에만 넣고, 없으면 `no flows selected` 를 명시한다.

### 8. A 기준 브랜치에서 capture

사람이 baseline 브랜치 checkout + dev 서버 기동. Claude 가:

```bash
python3 -u capture.py --plan <root>/.claude/migration-runtime-check/check-plan-<app>.json \
  --side A --out <root>/.claude/migration-runtime-check/run-1 --timeout 12000 \
  --retries 2 --settled-snapshot-ms 1000
```

`--retries` 는 scenario 내부 즉시 재시도가 아니다. 한 side 의 initial capture 를 모두 끝낸 뒤 retry 후보만 모아서 다시 캡처하는 pass 수다. retry 결과는 같은 `<branch>/<contextId>/pages/<scenarioId>/` 폴더를 삭제 후 다시 써서 덮어쓴다. 예: A initial capture 중 한 페이지에서 일시적 network/pageerror/requestfailed/about:blank/zero-actions/expectedFinalPath mismatch 가 발생하면 A 전체 종료 후 해당 scenario 만 retry 하고, 그 결과 폴더가 최종 A evidence 가 된다. 그 다음에 B 를 시작한다.

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
- 결과물은 branch 디렉터리 아래에서 context 단위로 먼저 끊는다:
  `<branchName>/<contextId>/pages/<scenarioId>`.
- scenarioId 로 A/B join
- check-plan 의 `knownUnstable` 패턴은 classes / texts / non-error console 신호에만 substring 매칭. 매칭된 신호는 main diff 가 아니라 **Noise Candidates** 섹션으로 분리.
- finalUrl / actions / pageerror / requestfailed / components / headings 는 noise 분류 대상 아님 (항상 main diff).
- report 에 비정상 시그널이 있으면 해당 시그널에서 일반 검색 가능한 문자열 조각을 뽑아 repo 의 `apps/`, `libs/` 를 자동 탐색한다. 대상은 DOM class 이름, 컴포넌트/엘리먼트 이름, 액션 이름, 콘솔·pageerror 첫 줄처럼 코드에 남아 있을 가능성이 높은 문자열이다. `rg --fixed-strings` 결과를 `Codebase Search` 섹션에 후보 파일/라인으로 붙인다. 이건 원인 확정이 아니라 코드 조사 시작점이다.
- check-plan 을 못 찾으면 `knownUnstable=[]` 로 계속 동작하되 report Summary 에 `check-plan not loaded` 표시.
- compare 는 각 branch 디렉터리의 `stamp.json.side` 로 baseline(A) / candidate(B)를 식별한다. 디렉터리 이름을
  `A` / `B` 로 가정하지 않는다.
- main diff 가 없고 노이즈만 잡힌 scenario 는 **Differences 섹션에서 제외**되고 별도 `## Noise-only Scenarios` 섹션에 scenarioId + noise 요약으로 표시. Summary 에 `noise-only scenarios` 카운트도 추가.
- initial snapshot 에서만 차이가 있고 `settled` snapshot 에서 차이가 사라지면 `transient page diff` 로 표시한다. 이는 flicker/초기 렌더 타이밍 신호이지 최종 화면 차이로 단정하지 않는다.

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
  "auth": { "storageState": ".auth/libs-app.json", "actor": "<actor-id>", "role": "<opaque-role>" },
  "knownUnstable": ["<unstable-fragment>"],
  "contexts": [
    {
      "id": "<context-id>",
      "auth": null,
      "vars": { "<route_or_state_key>": "<value>" },
      "labels": ["<opaque-label>"],
      "metadata": {
        "<user-provided-domain-key>": "<user-provided-domain-value>",
        "검증 의도": "<user-provided-intent>"
      }
    }
  ],
  "scenarios": [
    {
      "id": "<scenario-id>",
      "reason": "<why-this-scenario-matters>",
      "routeTemplate": "/resource/:resource_id/page",
      "context": "<context-id>",
      "path": "/resource/123/page",
      "expectedFinalPath": "/resource/123/page",
      "compare": ["page-capture", "action-surface", "user-flows", "console-runtime"],
      "flows": [
        {
          "id": "<flow-id>",
          "kind": "safe-ui-flow",
          "description": "<user-described-action>",
          "intent": "<why-the-user-does-this-action>",
          "expectedObservables": ["<what-should-be-visible-after-the-action>"],
          "snapshotAfterEachStep": true,
          "steps": [
            {
              "type": "click",
              "description": "<click-description>",
              "selector": "[data-testid='<stable-id>']"
            }
          ]
        }
      ]
    }
  ]
}
```

### Approved safe user flow 정책 (v1)

- check-plan 의 `scenarios[].flows[]` 에 명시된 flow 만 실행. extract.js 가 발견한 action 을 자동 순회 X.
- v1 지원 step 타입: `click` 만.
- v1 비목표: navigation flow, form submit / save / delete / create / update / send / payment 같은 mutating flow, flow 후보 자동 생성, pixel diff.
- selector 정책: `[data-testid=...]` 우선, `aria-label` / `role`+`name` 가능, **generated class selector 금지**.
- step 의 `step.json` status 값:
  - `ok` — click 성공, finalPath 변화 없음
  - `selector-not-found` / `selector-ambiguous` — locator count != 1
  - `unsafe-selector` — selector 에 `.ng-` / `.cdk-` / `.mat-mdc-` / `_ngcontent` / `_nghost` 패턴 포함 → click 실행하지 않음
  - `navigation-detected` — click 후 `finalPath` 가 변경됨 → safe-ui-flow 범위 이탈 evidence
  - `error` — selector 평가 또는 click 자체에서 예외
  - `skipped` — 같은 flow 의 이전 step 이 정상 완료되지 못해 후속 step 실행 안 함
- flow 결과는 diff 가 아니라 **evidence**. pass/fail 판정 X.
- 각 step 직후 `snapshotAfterEachStep` (default true) 이면 view/actions/runtime/meta + screenshot 저장. `unsafe-selector` step 은 page 상태가 변하지 않으므로 snapshot 생략.

step.json 예시 (ok):

```json
{
  "flowId": "<flow-id>",
  "step": 1,
  "type": "click",
  "selector": "[data-testid='<stable-id>']",
  "status": "ok",
  "error": null,
  "beforeFinalPath": "/resource/123/page",
  "afterFinalPath": "/resource/123/page"
}
```

step.json 예시 (failure):

```json
{
  "flowId": "<flow-id>",
  "step": 1,
  "type": "click",
  "selector": "[data-testid='<stable-id>']",
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
- `settled` snapshot 이 있으면 같은 비교를 한 번 더 수행해 initial-only 신호를 transient 로 분리

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

invalid 는 회귀 판정이 아니라 계획/캡처 품질 신호다.

- A/B 중 한쪽만 다른 finalPath → `side-specific-navigation`
- A/B 둘 다 같은 비예상 non-blank path → `plan-expectedFinalPath-mismatch`. dry-run 으로 실제 redirect 를 확인한 뒤 plan 보정
- A/B 둘 다 `about:blank` + actions=0 → `capture-not-ready`. capture timing / dev server / auth / route stability 문제로 보고 재시도 또는 wait 보강
- A/B 둘 다 서로 다른 비예상 path → `both-sides-navigation`

screenshot 은 비교 대상 X (픽셀 비결정성). `page.png` 는 증거로 보존하고 report 의 Page Capture 섹션에 경로만 표시.

## report.md 구조

```
# Migration Runtime Check Report

## Summary
- total scenarios: N
- scenarios with differences: K
- noise-only scenarios: M
- invalid captures: I
- transient page diffs: T
- A-only scenarios: x
- B-only scenarios: y
- (check-plan not loaded — 자동 로드 실패 시에만)
### Category counts (scenarios affected)
- Page Capture: a
- Action Surface: b
- User Flows: f
- Console / Runtime: c

## Invalid Captures
### <scenarioId>
- expected: <expectedFinalPath>
- A finalPath: ...
- B finalPath: ...
- reason: <which side mismatched>
- reasonKind: capture-not-ready | plan-expectedFinalPath-mismatch | side-specific-navigation | both-sides-navigation
- actions: A=n B=m
- deep diff: skipped

## Differences
### <scenarioId>
Context:
- auth: ...
- vars: ...
- labels: tag1, tag2
- metadata:
  - <user-provided-domain-key>: "..."
  - <another-user-provided-domain-key>: "..."

#### Page Capture
- screenshot:
  - A: <baselineBranch>/<contextId>/pages/<scenarioId>/page.png
  - B: <candidateBranch>/<contextId>/pages/<scenarioId>/page.png
- timing: initial snapshot differs, delayed settled snapshot has no remaining page/action/runtime diff  # transient 일 때만
- (finalUrl / title / components / classes / headings / texts / whiteScreen — 차이 있을 때만)

#### Action Surface      # 차이 있을 때만 섹션 등장
- ...

#### Console / Runtime    # 차이 있을 때만
- ...

#### User Flows    # flow 실행 + 결과 차이 있을 때만
##### <flowId> / step-<N>
- step:
  - A: ok
  - B: selector-not-found
- screenshot:
  - A: <baselineBranch>/<contextId>/pages/<scenarioId>/flows/<flowId>/step-<N>/page.png
  - B: <candidateBranch>/<contextId>/pages/<scenarioId>/flows/<flowId>/step-<N>/page.png
- differences:    # 양쪽 status 가 ok 일 때 step capture diff 요약
  - headings: +1 -1
  - ...

#### Noise Candidates    # 매칭된 항목 있을 때만
- ...

#### Codebase Search     # 비정상 시그널 기반 자동 탐색 후보가 있을 때만
- pattern: `<signal-fragment>`
  - `<source-path>:<line>` ...

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
- `networkidle` wait 는 HMR websocket 때문에 안 떨어질 수 있다. `domcontentloaded` + route stability + bounded retry.
- capture 는 기본적으로 `about:blank` 에 머문 scenario 를 2회 재시도하고, 정상 URL 도달 후 1초 지연 `settled` snapshot 을 추가 저장한다. initial snapshot 은 초기 렌더 회귀를 잡기 위한 것이고, settled snapshot 은 최종 화면 차이를 분리하기 위한 것이다.
- 동시에 한 사이드만 캡처. workers=1. 결정성 우선.

## 비목표

- flow 후보 자동 생성 / extract.js actions 자동 순회
- mutating flow (form submit, save, delete, create, update, send, payment 등)
- navigation flow (v1 범위 외)
- v1 외 step 타입 (현재 `click` 만)
- transition 검증
- CI 통합
- 자동 pass/fail 판정 / 4상태 라벨
- pixel diff / computed style diff
- screenshot diff
- legacy route-based pageId / discover-positional capture (폐기됨)
