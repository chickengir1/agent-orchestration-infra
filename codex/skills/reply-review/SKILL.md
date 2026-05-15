---
name: reply-review
description: Draft or post replies to GitHub pull request review comments. Use for PR 리뷰 답글, 리뷰 코멘트 응답, bot 리뷰 대응, 사람 리뷰어 존댓말 답변, gh api review-comment replies, in_reply_to thread replies.
---

# Reply Review

PR-level 댓글이 아니라 특정 review thread에 답한다. 기본 출력 언어는 한국어다. 리뷰 코멘트가 영어이거나 사용자가 영어 답변을 원하면 영어로 답한다.

## Workflow

1. owner, repo, PR 번호, 대상 리뷰 코멘트를 확인한다. 가능하면 `gh repo view --json owner,name`로 owner/repo를 추론한다.
2. 리뷰 코멘트 목록을 가져온다:

```bash
gh api repos/{owner}/{repo}/pulls/{pr}/comments
```

3. 사용자가 준 맥락, 코멘트 본문, 파일 경로, 라인, 리뷰어를 기준으로 대상 comment id를 찾는다.
4. 현재 diff와 주변 코드 패턴을 확인한다. 답변은 감상이 아니라 코드 근거에 기반해야 한다.
5. 답글 초안을 작성한다.
   - 사람 리뷰어: 한국어 존댓말, 짧지만 맥락 있게 답한다.
   - 봇 리뷰어: 근거 중심으로 짧게 답한다.
   - 리뷰어가 맞으면 무엇을 반영했는지 또는 반영할지 말한다.
   - 반영하지 않는다면 어떤 제약, 불변식, 기존 패턴 때문에 유지하는지 설명한다.
6. 사용자가 바로 게시하라고 명시하지 않았다면 먼저 답글 초안을 보여준다.
7. 게시할 때는 반드시 `in_reply_to`를 사용한다:

```bash
gh api repos/{owner}/{repo}/pulls/{pr}/comments \
  -F "in_reply_to={comment_id}" \
  -f "body=$(cat /tmp/pr-reply.txt)"
```

8. 임시 답글 파일은 게시 후 제거한다.

## Reply Rules

- `gh pr comment`를 쓰지 않는다. review thread에는 `in_reply_to`로 답한다.
- `@mention`이나 특수문자가 포함될 수 있으므로 답글 본문은 임시 파일에 쓰고 전달한다.
- 기본 톤은 한국어 존댓말이다.
- 사람 리뷰어에게는 방어적으로 쓰지 말고, 변경/유지 판단의 근거를 명확히 쓴다.
- 봇 리뷰어에게는 장황한 설명을 피하고, false positive인지 수정 완료인지 핵심만 쓴다.
- 기존 코드 패턴, public contract, 설계 경계, 테스트 결과 중 하나 이상으로 답변을 뒷받침한다.
- 리뷰어가 맞는 경우 우회적으로 말하지 않는다. 반영했다고 명확히 쓴다.
- 스레드 resolve는 사용자가 요청하고 사용 가능한 명령이 있을 때만 한다.

## Good Reply Shapes

수정 반영:

```text
+ 반영했습니다. 말씀하신 케이스에서 read/write 권한 불변식이 component 이벤트 순서에 의존할 수 있어서, store의 toggle 메서드에서 보장하도록 옮겼습니다.
```

유지 설명:

```text
+ 이 부분은 유지하는 쪽이 맞다고 봤습니다. 해당 값은 legacy read contract에서 guard와 shared component가 같이 사용하고 있어서, v2 전용 정규화 모델로 덮어쓰면 기존 화면의 판정이 바뀔 수 있습니다.
```

봇 리뷰 대응:

```text
+ false positive입니다. 이 값은 외부 입력이 아니라 `BoardEntity` 정규화 이후의 내부 enum이며, 저장 전 `toWritePayload`에서 다시 제한됩니다.
```
