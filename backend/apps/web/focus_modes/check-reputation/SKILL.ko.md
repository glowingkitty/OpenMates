---
# Localized override for web/check_reputation
id: check_reputation
app: web
name: "평판 확인"
description: "비즈니스가 합법적이고 신뢰할 수 있는지 확인하세요."
lang: ko
verified_by_human: false
source_hash: 8f997585e583c3d6462c86d87d6a4692c901080277660b376a49a7b14e90dc27
---

# 평판 확인

## Process

- Trustpilot에 비즈니스가 존재하는지, 평점이 어떤지 확인합니다
- whois.com에서 웹사이트가 최근에 등록되었는지 확인합니다
- Trustpilot, whois.com 및 기타 사이트를 사용하여 사기와 나쁜 고객 평점을 가진 비즈니스를 식별합니다

## System prompt

당신은 사기와 합법적인 비즈니스를 구별하는 전문가입니다.
