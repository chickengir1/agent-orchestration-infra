# Reply Review

PR 리뷰 코멘트에 답글을 단다.

## Trigger

`/reply-review` 또는 PR 리뷰 코멘트에 답글 요청 시.

## Instructions

1. 유저가 PR 번호와 답글 맥락을 제공한다.
2. `gh api repos/{owner}/{repo}/pulls/{pr}/comments`로 리뷰 코멘트 목록을 가져온다.
3. 해당 코멘트의 `id`를 찾는다.
4. 답글 내용을 `/tmp/pr-reply.txt`에 작성한다.
5. 유저에게 내용을 보여주고 컨펌을 받는다.
6. 파일 내용을 변수로 읽어서 답글을 단다:
   ```bash
   BODY=$(cat /tmp/pr-reply.txt) && gh api repos/{owner}/{repo}/pulls/{pr}/comments -F "in_reply_to={comment_id}" -f "body=$BODY"
   ```
7. `/tmp/pr-reply.txt`를 삭제한다.

## Rules

- `in_reply_to`로 해당 리뷰 스레드에 개별 답글
- `gh pr comment` (PR-level 코멘트) 사용 금지
- `@멘션` 포함 시 파싱 에러가 나므로 반드시 파일 경로로 전달
- 봇 리뷰어에게는 짧게 근거만 제시
- 사람 리뷰어에게는 존댓말로 답변
- 기존 코드 패턴과 비교하여 근거 제시
- 한 줄을 너무 길게 쓰지 않음
- 쉼표로 계속 이어 쓰지 않고 줄바꿈으로 분리
