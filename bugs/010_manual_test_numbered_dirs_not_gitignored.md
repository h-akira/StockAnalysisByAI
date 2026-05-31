# BUG-010: 連番付き manual_test_NN/ ディレクトリが gitignore 対象外

## ステータス

修正済み（検証済み）

## 発見日

2026-05-31

## 概要

ルート `.gitignore` には `manual_test/`（末尾スラッシュ・単数形）のみが登録されており、`manual_test_01/` `manual_test_02/` のような連番付きディレクトリはマッチしない。結果、4.86MB の HTML を含むレビュー用ディレクトリが丸ごと commit に紛れ込む経路が実在する（[BUG-008](008_potential_report_commit_leakage.md) と同種のリスクが Skill 外で再燃）。

## 症状

- `git check-ignore manual_test_02/report_9531.html` が exit 1（NOT ignored）を返す。
- `git status` に `manual_test_01/` `manual_test_02/`（成果物 5 ファイル含む）が untracked で表示される。
- AGENTS.md は `manual_test/` を「gitignore 済の手動テスト領域」としているが、実体である連番ディレクトリはカバーされていない。

## 原因

- ルート `.gitignore` の登録は `manual_test/` のみ（[.gitignore:12](../.gitignore#L12)）。gitignore の `manual_test/` パターンは厳密に `manual_test` という名前のディレクトリにのみマッチし、`manual_test_01` `manual_test_02` にはマッチしない。
- 手動テストを連番ディレクトリで運用する実態と、gitignore パターンが乖離している。

## 影響範囲

- ルート `.gitignore`
- `git add .` / `git add -A` を使った場合の commit（CLAUDE.md でこれらは禁止のため最後の砦はルール運用）。
- BUG-008 の `.gitignore` 防御は「Skill 配下に出た成果物」専用で、CWD 側（`manual_test_NN/`）は守備範囲外。

## 再現手順

1. リポジトリルートで `git check-ignore manual_test_02/report_9531.html`
2. exit code が 1（NOT ignored）であることを確認
3. `git status` に `manual_test_02/` が untracked として現れることを確認

## 修正案

### 案1: glob パターンで連番ディレクトリを包含（推奨）

ルート `.gitignore` に `manual_test*/`（または `manual_test_*/`）を追加する。既存の `manual_test/` も包含できる。AGENTS.md の記述（`manual_test/` が手動テスト領域）も連番運用に合わせて一文補足する。

### 案2: 連番をやめて manual_test/ 配下にサブディレクトリ運用

`manual_test/01/` `manual_test/02/` のように既存パターン配下へ収める。ただし既存の `manual_test_01/` `manual_test_02/` の移動が必要で運用変更コストがある。

> 案1 が低コストかつ確実。あわせて成果物の拡張子（`report_*.html` 等）が万一トラッキングされないよう注意。

## 対応

案1 を採用。

- `.gitignore`: 既存 `manual_test/` に加えて `manual_test_*/` を追加（連番ディレクトリを包含）。説明コメントも追記。
- `AGENTS.md`: リポジトリ構成図の `manual_test/` を `manual_test*/` に変更し「連番 manual_test_NN/ 含め gitignore 済」と補足。

検証: `git check-ignore manual_test_02/report_9531.html manual_test_01/ manual_test/` が全パスマッチ（exit 0）。連番ディレクトリが無視対象になったことを確認。

## 関連

- レビュー: [manual_test_02/review_report.md](../manual_test_02/review_report.md) §4.3
- [BUG-008](008_potential_report_commit_leakage.md): Skill 配下の成果物 commit 漏洩（同種・別領域）
