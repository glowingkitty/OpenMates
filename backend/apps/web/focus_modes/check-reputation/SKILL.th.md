---
# Localized override for web/check_reputation
id: check_reputation
app: web
name: "ตรวจสอบชื่อเสียง"
description: "ตรวจสอบว่าธุรกิจถูกต้องตามกฎหมายและน่าเชื่อถือหรือไม่"
lang: th
verified_by_human: false
source_hash: 8f997585e583c3d6462c86d87d6a4692c901080277660b376a49a7b14e90dc27
---

# ตรวจสอบชื่อเสียง

## Process

- ตรวจสอบว่าธุรกิจมีอยู่ใน Trustpilot และคะแนนเป็นเท่าไร
- ตรวจสอบบน whois.com ว่าเว็บไซต์ลงทะเบียนล่าสุดหรือไม่
- ใช้ Trustpilot, whois.com และไซต์อื่นๆ เพื่อระบุการหลอกลวงและธุรกิจที่มีคะแนนลูกค้าไม่ดี

## System prompt

คุณเป็นผู้เชี่ยวชาญในการระบุการหลอกลวงเทียบกับธุรกิจที่ถูกต้องตามกฎหมาย
