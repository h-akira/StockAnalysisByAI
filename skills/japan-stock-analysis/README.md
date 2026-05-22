# japan-stock-analysis Skill

日本株（4桁証券コード）の個別分析を Claude Code から実行するための Agent Skill です。
詳細設計は本リポジトリ直下の [plan.md](../../plan.md) と [pre-research/](../../pre-research/) を参照してください。

## 概要

- **入力**: 証券コード（例: `7203`）。1〜数社（〜10社）まで。
- **出力**: 現在の作業ディレクトリに `report_{sec_code}.html` と `data_{sec_code}.json` を生成。
- **データソース**: EDINET（一次情報、財務本体）+ yfinance（最新株価・PER/PBR スナップショット補完）。
- **キャッシュ**: 本 Skill 内 `cache/` に保持（gitignore）。

## セットアップ

1. EDINET API キーを取得し、Skill ルート直下に `secret.json` を配置する。

   ```json
   {
     "edinet": {
       "api_key": "<your key>"
     }
   }
   ```

   `secret.json` は `.gitignore` 済みです。誤コミット防止のため git status で確認してください。

2. 仮想環境を作成し依存をインストール。

   ```bash
   python -m venv env
   source env/bin/activate
   pip install -r requirements.txt
   ```

3. 初回のみ bootstrap。

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/bootstrap.py init
   ```

   ※ Claude Code 経由で起動する場合は `${CLAUDE_SKILL_DIR}` が自動セットされる。
   手動で実行する場合は `CLAUDE_SKILL_DIR=$(pwd)` を Skill ルートで先に設定する。

## 開発状況

本 Skill は段階的に実装中です。各 Phase の進捗は [plan.md §5](../../plan.md) を参照。

| Phase | 状態 |
|-------|------|
| P1: 骨組み | 進行中 / 完了 |
| P2: bootstrap | 未着手 |
| P3: 分析ロジック移植 | 未着手 |
| P4: 株式分割補正 | 未着手 |
| P5: HTML/JSON テンプレ化 | 未着手 |
| P6: エラー処理・キャッシュ管理 | 未着手 |
| P7: テスト | 未着手 |
| P8: SKILL.md 整備 + AI エスカレーション | 未着手 |
| P9: 通し動作確認 | 未着手 |
| P10 (将来): 株価チャート | 未着手 |

## 動作確認

```bash
# キャッシュ状態の表示（JSON）
python3 ${CLAUDE_SKILL_DIR}/scripts/cache_admin.py info

# 銘柄別キャッシュ状態の表示
python3 ${CLAUDE_SKILL_DIR}/scripts/cache_admin.py info --sec-code 7203

# 1銘柄の分析（任意の CWD から実行 → CWD に report_*.html が出る）
python3 ${CLAUDE_SKILL_DIR}/scripts/pipeline.py analyze --sec-code 7203
```

## 設計メモ: 呼び出し方針

[Claude Code Agent Skills 公式](https://code.claude.com/docs/en/skills) の慣習に従い、
スクリプトは `${CLAUDE_SKILL_DIR}` 環境変数による**絶対パスで直接実行**する。
これにより CWD はユーザーのプロジェクトディレクトリのままで、スクリプトは
Skill 配下を絶対パスで参照する。

開発時 (pytest 等) の都合で `python -m scripts.X` 形式でも動くように
各 CLI スクリプトの先頭で sys.path 調整が入っている。本番運用 (SKILL.md) では
常に `${CLAUDE_SKILL_DIR}` 絶対パス方式を使う。
