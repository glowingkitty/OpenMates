---
# Localized override for code/test_git_repo
id: test_git_repo
app: code
name: "测试git仓库"
description: "克隆git仓库并测试它是否工作。"
lang: zh
verified_by_human: false
source_hash: 4f29005037badc1c1de458029057dc8d03eb29fdddd15c1ba78b867b6e54b567
---

# 测试git仓库

## Process

- 如果尚未提供，请用户提供 github/gitlab 仓库 URL
- 如果尚未提供，询问用户想测试什么/他们的使用场景是什么
- 使用技能检查 issues，看是否有最近报告的关于使用该仓库的关键问题
- 如果项目被报告为损坏，询问用户是否要继续测试
- 询问用户在哪里克隆和测试仓库？设置新机器？使用 github codespaces？本地机器？等
- 将仓库克隆到指定位置
- 阅读项目文件夹和文件结构以及 readme.md，了解项目概况
- 找出如何测试项目并开始测试
