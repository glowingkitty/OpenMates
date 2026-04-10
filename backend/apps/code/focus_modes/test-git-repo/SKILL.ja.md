---
# Localized override for code/test_git_repo
id: test_git_repo
app: code
name: "Gitリポジトリをテスト"
description: "Gitリポジトリをクローンし、動作するかテストします。"
lang: ja
verified_by_human: false
source_hash: 4f29005037badc1c1de458029057dc8d03eb29fdddd15c1ba78b867b6e54b567
---

# Gitリポジトリをテスト

## Process

- まだ提供されていない場合、ユーザーに github/gitlab リポジトリの URL を尋ねる
- まだ提供されていない場合、ユーザーにテストしたいこと / ユースケースを尋ねる
- スキルを使用して、リポジトリ使用に関する最近報告された重大な問題を issues で確認する
- プロジェクトが壊れていると報告された場合、ユーザーにテストを続けるかどうか尋ねる
- ユーザーにリポジトリをクローンしてテストする場所を尋ねる（新しいマシン設定? github codespaces? ローカルマシン? など）
- リポジトリを指定された場所にクローンする
- プロジェクトのフォルダ・ファイル構造と readme.md を読んでプロジェクトの概要を把握する
- プロジェクトのテスト方法を把握してテストを開始する
