---
description: AI 기본법에 대해 질문하고 조문 근거가 붙은 답을 받는다
argument-hint: <질문 또는 조문 번호>
---

AI 기본법 질문: $ARGUMENTS

`law-citation` 스킬을 따라 답한다.

- 입력이 조문 번호(예: "33", "제33조")이면 `get_article`로 원문을 가져와 조·항별로 정리한다.
- 그 밖의 질문이면 `ask_law`로 답을 받고, sources의 조문을 `get_article`로 확인한 뒤 인용과 함께 답한다.
- 입력이 비어 있으면 `law://ai-basic-act/toc` 목차를 보여 주고 무엇을 찾을지 묻는다.
