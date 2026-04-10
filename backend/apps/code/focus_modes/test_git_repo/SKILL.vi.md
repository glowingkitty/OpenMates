---
# Localized override for code/test_git_repo
id: test_git_repo
app: code
name: "Kiểm tra kho git"
description: "Sao chép kho git và kiểm tra xem nó có hoạt động không."
lang: vi
verified_by_human: false
source_hash: 4f29005037badc1c1de458029057dc8d03eb29fdddd15c1ba78b867b6e54b567
---

# Kiểm tra kho git

## Process

- nếu chưa được cung cấp, yêu cầu người dùng URL kho lưu trữ github/gitlab
- nếu chưa được cung cấp, hỏi người dùng muốn kiểm tra gì / trường hợp sử dụng của họ là gì
- sử dụng kỹ năng để kiểm tra issues xem có vấn đề nghiêm trọng nào được báo cáo gần đây không
- nếu dự án được báo cáo là bị hỏng, hỏi người dùng có muốn tiếp tục kiểm tra không
- hỏi người dùng sẽ clone và kiểm tra kho lưu trữ ở đâu: máy mới? github codespaces? máy cục bộ? v.v.
- clone kho lưu trữ đến vị trí đã chỉ định
- đọc cấu trúc thư mục và tệp của dự án và readme.md để có cái nhìn tổng quan
- tìm hiểu cách kiểm tra dự án và bắt đầu kiểm tra
