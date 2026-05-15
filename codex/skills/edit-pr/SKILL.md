---
name: edit-pr
description: Draft or update GitHub pull request titles and bodies. Use for PR 제목/본문 작성, PR body 수정, 템플릿 채우기, conventional commit title, gh pr view/diff, what+why 한국어 PR 설명, 작업 범위/테스트 방법 정리.
---

# Edit PR

GitHub CLI 정보와 diff를 바탕으로 PR 제목/본문을 작성하거나 수정한다. 기본 출력 언어는 한국어다. 기존 PR 템플릿이나 사용자가 지정한 언어가 영어면 그 언어를 따른다.

## Workflow

1. PR 번호를 확인한다. 생략된 경우 현재 브랜치에서 `gh pr view --json number,title,body,headRefName,baseRefName`로 찾는다.
2. 현재 PR 정보는 `gh pr view <PR> --json title,body,headRefName,baseRefName`로 읽는다.
3. 변경사항은 `gh pr diff <PR>`로 확인한다. PR이 없으면 로컬 `git diff`를 사용하고 한계를 명시한다.
4. 기존 PR 본문 템플릿 구조를 보존한다. 체크박스, 섹션 제목, 구분선, 안내 문구를 임의로 삭제하거나 재구성하지 않는다. 명백한 예시 섹션만 제거한다.
5. 한국어 템플릿이면 해당 섹션을 자연스럽게 채운다:
   - PR 유형
   - Notion Issue Card Link 또는 이슈 링크
   - 작업 범위
   - 기능 요약
   - 주요 변경사항
   - 테스트 방법
   - 기타 참고 사항
6. 주요 변경사항은 파일 나열이 아니라 what + why로 쓴다. 리뷰어가 diff를 보지 않아도 설계 의도와 영향 범위를 이해할 수 있어야 한다.
7. 검증 결과, 파일 목록, 비교표, API trace, 상세 정책은 본문을 압도하지 않도록 `<details><summary>...</summary>` 블록에 넣는다.
8. GitHub 상태를 변경하기 전에는 제목/본문 초안을 보여주거나 실행할 명령을 명확히 밝힌다. 사용자가 업데이트 의도를 명확히 했을 때만 `gh pr edit`를 실행한다.

## Title Rules

- 로컬 convention이 있으면 따른다.
- 기본 형식은 `feat:`, `fix:`, `refactor:`, `test:`, `chore:` 같은 conventional commit prefix를 사용한다.
- 프로젝트/도메인 scope가 관례면 포함한다.
- 제목은 변경의 결과를 말한다. 작업 행위 자체를 제목으로 삼지 않는다.

## Body Rules

- 기본 문체는 한국어, 직접적이고 간결한 설명.
- 사용자가 제공한 워크스코프, 프로젝트명, 키워드는 그대로 반영한다.
- 회사 템플릿 원본을 삭제하거나 재배열하지 않는다.
- PR 본문은 리뷰어가 판단하는 데 필요한 정보만 전면에 둔다.
- 설계 의도, 호환성 유지, fallback, 마이그레이션, 의도적으로 하지 않은 작업은 명시한다.
- 과도한 볼드, 장식적 마크다운, 반복 설명은 피한다.
- 테스트를 실행하지 않았으면 실행하지 않았다고 쓴다. 추정으로 검증했다고 쓰지 않는다.

## Failure Handling

- `gh`가 없거나 인증이 안 되어 있으면 로컬 diff 기반 초안을 작성하고 제한을 말한다.
- PR 템플릿이 없으면 짧은 표준 구조를 제안하되, 사용자가 지정한 형식이 있으면 우선한다.
- diff가 너무 크면 주요 경계, 사용자 영향, 검증 방법, 위험 순서로 압축한다.
