---
# Localized override for code/test_git_repo
id: test_git_repo
app: code
name: "Git 저장소 테스트"
description: "Git 저장소를 복제하고 작동하는지 테스트하세요."
lang: ko
verified_by_human: false
source_hash: 4f29005037badc1c1de458029057dc8d03eb29fdddd15c1ba78b867b6e54b567
---

# Git 저장소 테스트

## Process

- 아직 제공되지 않은 경우 사용자에게 github/gitlab 저장소 URL을 요청합니다
- 아직 제공되지 않은 경우 사용자에게 무엇을 테스트하고 싶은지 / 사용 사례가 무엇인지 묻습니다
- 기술을 사용하여 저장소 사용과 관련해 최근 보고된 중요한 이슈가 있는지 확인합니다
- 프로젝트가 작동하지 않는다고 보고된 경우 사용자에게 계속 테스트할지 묻습니다
- 사용자에게 저장소를 어디서 클론하고 테스트할지 묻습니다 (새 머신 설정? github codespaces? 로컬 머신? 등)
- 지정된 위치에 저장소를 클론합니다
- 프로젝트 폴더 및 파일 구조와 readme.md를 읽어 프로젝트 개요를 파악합니다
- 프로젝트를 테스트하는 방법을 파악하고 테스트를 시작합니다
