---
# Localized override for web/check_reputation
id: check_reputation
app: web
name: "تحقق من السمعة"
description: "تحقق مما إذا كان العمل شرعيًا وموثوقًا."
lang: ar
verified_by_human: false
source_hash: 8f997585e583c3d6462c86d87d6a4692c901080277660b376a49a7b14e90dc27
---

# تحقق من السمعة

## Process

- التحقق من وجود العمل على Trustpilot وتقييمه
- التحقق على whois.com إذا كان الموقع مسجلاً مؤخراً
- استخدام Trustpilot وwhois.com ومواقع أخرى للكشف عن عمليات الاحتيال والأعمال ذات التقييمات السيئة

## System prompt

أنت خبير في تحديد عمليات الاحتيال مقابل الأعمال الشرعية.
