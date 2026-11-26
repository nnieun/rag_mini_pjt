---
description: AI 서비스 설명을 받아 AI 기본법상 의무를 점검표로 정리한다
argument-hint: <서비스 설명>
---

점검할 서비스: $ARGUMENTS

서비스 설명이 비어 있거나 판단에 필요한 정보가 빠졌으면 먼저 한 번에 묻는다.

1. `create_compliance_report`(service_description)로 점검 에이전트를 실행한다.
2. 결과의 판정, 해당 목, 해당 의무를 `compliance-check` 스킬의 표 형식으로 정리하고, 근거 조문은 `get_article`로 확인해 인용한다.
3. status가 completed면 report_url(PDF)을 알려 준다. awaiting_approval이면 사람 검토가 필요한 이유(review_reasons)와 승인 방법(message)을 그대로 전한다. 직접 승인하지 않는다.
4. 도구를 쓸 수 없으면 `compliance-check` 스킬의 수동 절차로 점검한다.
