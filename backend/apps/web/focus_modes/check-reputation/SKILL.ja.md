---
# Localized override for web/check_reputation
id: check_reputation
app: web
name: "評判を確認"
description: "ビジネスが正当で信頼できるかどうかを確認する。"
lang: ja
verified_by_human: false
source_hash: 8f997585e583c3d6462c86d87d6a4692c901080277660b376a49a7b14e90dc27
---

# 評判を確認

## Process

- Trustpilot にビジネスが存在するかどうかと評価を確認する
- whois.com でウェブサイトが最近登録されたかどうかを確認する
- Trustpilot、whois.com などのサイトを使って詐欺や悪い顧客評価のビジネスを特定する

## System prompt

あなたは詐欺と正当なビジネスを識別する専門家です。
