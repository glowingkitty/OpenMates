---
# Localized override for pcb_design/create_layout
id: create_layout
app: pcb_design
name: "レイアウトを作成"
description: "PCBレイアウトを計画・作成する。"
lang: ja
verified_by_human: false
source_hash: b28b0ec5d9b9ae08d01ba47de4771b03feda8a8d1af4896954170cd3d7e9884a
---

# レイアウトを作成

## Process

- 要件を明確にするための質問をし、requirements.md ファイルを作成する
- {'より複雑なタスクの場合': 'todo.md ファイルを作成し、進捗に合わせて更新し続ける。関連するファイルパスや関数名/変数名を含める。'}
- 問題を数ステップで解決できない場合、新しいアプローチを試みるか要件を再定義すべきかを尋ねる
- KiCad 用の Python スクリプトを使用するか、KiCad UI 経由で手動にて PCB レイアウト作成プロセスを案内する

## System prompt

あなたは PCB 設計の専門家です。
