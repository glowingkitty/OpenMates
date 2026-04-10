---
# Localized override for web/check_reputation
id: check_reputation
app: web
name: "Kiểm tra danh tiếng"
description: "Kiểm tra doanh nghiệp có hợp pháp và đáng tin không."
lang: vi
verified_by_human: false
source_hash: 8f997585e583c3d6462c86d87d6a4692c901080277660b376a49a7b14e90dc27
---

# Kiểm tra danh tiếng

## Process

- kiểm tra xem doanh nghiệp có tồn tại trên Trustpilot và điểm đánh giá của họ
- kiểm tra trên whois.com xem trang web có được đăng ký gần đây không
- sử dụng Trustpilot, whois.com và các trang web khác để xác định gian lận và các doanh nghiệp có đánh giá khách hàng kém

## System prompt

Bạn là chuyên gia xác định gian lận so với doanh nghiệp hợp pháp.
