---
# Localized override for web/check_reputation
id: check_reputation
app: web
name: "检查声誉"
description: "检查企业是否合法可靠。"
lang: zh
verified_by_human: false
source_hash: 8f997585e583c3d6462c86d87d6a4692c901080277660b376a49a7b14e90dc27
---

# 检查声誉

## Process

- 检查企业是否在 Trustpilot 上存在及其评分
- 在 whois.com 上检查该网站是否是最近注册的
- 使用 Trustpilot、whois.com 及其他网站识别诈骗和客户评分差的企业

## System prompt

你是识别诈骗与合法企业的专家。
