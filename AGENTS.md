# AGENTS.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

日本株（4桁証券コード）の財務三表・指標・バリュエーション推移を EDINET と yfinance から取得し、HTML レポート / JSON データを生成する **Claude Code Agent Skill** を開発するプロジェクト。

最終成果物は `skills/japan-stock-analysis/` 配下に置かれた配布可能な Skill。利用者は同ディレクトリを `~/.claude/skills/` 等にコピーして Claude Code から呼び出す。

## リポジトリ構成

サブモジュールなしの単一リポジトリ。

```
FinanceSource/
├── AGENTS.md                  # 本ファイル（プロジェクト全体の指針）
├── CLAUDE.md                  # Claude Code 入口（@AGENTS.md をインポート）
├── init_plan.md               # 初期計画ドキュメント (Single Source of Truth)
├── skills/                    # Skill 開発ディレクトリ（最終成果物）
│   └── japan-stock-analysis/
│       ├── SKILL.md           # Skill エントリ手順書（Claude が読む）
│       ├── README.md          # 開発者向け説明 + 将来の課題
│       ├── docs/              # Skill 配布物に含まれる設計ドキュメント
│       │   ├── json_schema.md
│       │   ├── xbrl_variation_knowledge.md
│       │   └── p9_smoke_results.md
│       ├── scripts/           # 実装本体
│       ├── templates/         # Jinja2 HTML テンプレート
│       ├── tests/             # pytest（fixtures 含む）
│       └── cache/             # gitignore 済 (documents/xbrl/derived/...)
├── pre-research/              # 設計検証フェーズの実証スクリプトと記録（凍結）
│   └── edinet/
│       ├── step0_verify.py ... step7_split_adjust.py
│       ├── verification_plan.md
│       └── verification_results.md
├── bugs/                      # バグ管理
│   ├── XXX_template.md
│   └── 001_*.md, 002_*.md, ...
├── enhancements/              # 改善・仕様追加・改良管理
│   ├── XXX_template.md
│   └── 001_*.md, 002_*.md, ...
├── references/                # 外部参照資料の置き場（設計ドキュメントではない）
│   └── edinet/                # EDINET 公式仕様書 ESE140206.pdf 等（gitignore 済）
├── tmp/                       # 今後見返すかもしれない作業ファイル（README 参照）
├── old/                       # 説明済みや古い認識のアーカイブ（README 参照）
└── manual_test/               # 手動テスト用 (Skill コピー、history.md 等。gitignore 済)
```

**サブモジュールは無い。** ルートの `references/` は EDINET 公式仕様 PDF/XLSX の置き場であり設計ドキュメントではない。`tmp/` と `old/` は AI が通常作業時には参照しないアーカイブ領域。

## 設計ドキュメント（Single Source of Truth）

本プロジェクトの設計の正は以下に集約されている。実装着手前に必ず関連箇所を読むこと。

| ファイル | 責務 |
|---------|------|
| `init_plan.md` | **本プロジェクトの SSoT**。初期計画ドキュメント。全体設計、ディレクトリ構成、キャッシュポリシー、Phase 計画と完了条件、リスク管理 |
| `pre-research/edinet/verification_plan.md` | 設計検証フェーズの計画（Step 1〜7） |
| `pre-research/edinet/verification_results.md` | 設計検証の実機結果と教訓（株式分割問題、XBRL要素揺れ等） |
| `pre-research/edinet/xbrl_company_variation.md` | XBRL 会社別差異のナレッジ（本実装での対処方針含む） |
| `pre-research/edinet/edinet_api_overview.md` | EDINET API 仕様サマリ（公式仕様書からの要点抽出） |
| `skills/japan-stock-analysis/SKILL.md` | Skill 内のエントリ手順書（Claude が SKILL.md 起動時に読む） |
| `skills/japan-stock-analysis/README.md` | Skill 開発者向け説明と将来の課題一覧 |
| `skills/japan-stock-analysis/docs/json_schema.md` | `data_*.json` 出力の v1.0 スキーマ仕様 |
| `skills/japan-stock-analysis/docs/xbrl_variation_knowledge.md` | XBRL 要素マッピングのナレッジ（Claude が SKILL.md §6 で参照） |
| `skills/japan-stock-analysis/docs/p9_smoke_results.md` | Phase P9 通し動作検証の生データ |

設計過程の議論記録（必要に応じて参照、通常は不要）:
- `tmp/QA_skill_invocation.md`: Skill 起動方法（`${CLAUDE_SKILL_DIR}` 絶対パス方式）の設計議論と最終決定

`pre-research/` は**凍結**フェーズ。設計検証の証跡として残し、本実装ロジックは `skills/japan-stock-analysis/scripts/` に移植済み。

## バグ管理 (`bugs/`)

設計検証以降で発見されたバグを `bugs/` 配下に Markdown ファイルとして管理する。

- ファイル名: `XXX_（概要を表すスネークケース）.md`（`XXX` は 3 桁の連番、優先度順）
- テンプレート: `bugs/XXX_template.md` に従って作成すること
- ステータス: 「未修正」「対応不要」「修正済み（検証待ち）」「修正済み（検証済み）」「その他」のいずれか
- バグ修正時は、修正内容を「対応」セクションに追記し、ステータスを更新すること

## 改善管理 (`enhancements/`)

改善・仕様追加・改良を `enhancements/` 配下に Markdown ファイルとして管理する。

- ファイル名: `XXX_（概要を表すスネークケース）.md`（`XXX` は 3 桁の連番）
- テンプレート: `enhancements/XXX_template.md` に従って作成すること
- 種別: 「仕様追加」「改善」「改良」のいずれか
- ステータス: 「未着手」「対応中」「対応不要」「完了（検証待ち）」「完了（検証済み）」「その他」のいずれか
- 対応完了時は、対応内容を「対応」セクションに追記し、ステータスを更新すること

## Skill 実装上の規約

### スクリプト起動方法

Skill 内のスクリプトは **Claude Code Agent Skills 公式慣習**に従い `${CLAUDE_SKILL_DIR}` 絶対パスで起動する。`python -m scripts.X` ではなく `python3 ${CLAUDE_SKILL_DIR}/scripts/X.py` を使う。詳細は [tmp/QA_skill_invocation.md](tmp/QA_skill_invocation.md) と [SKILL.md](skills/japan-stock-analysis/SKILL.md) §4 を参照。

ただし開発時（pytest 等）の都合で `python -m scripts.X` 形式でも動くよう各 CLI スクリプト先頭に sys.path 調整スニペットが入っている。本番運用と SKILL.md 上は常に `${CLAUDE_SKILL_DIR}` 絶対パス方式を使う。

### 成果物の出力先

`report_*.html` / `data_*.json` などの分析成果物は **Claude 実行時の CWD**（ユーザーの作業ディレクトリ）に出力する。Skill 配下に出力してはならない（`init_plan.md` §3.4 / [BUG-001](bugs/001_output_lands_in_skill_dir_not_cwd.md)）。

### テスト

```bash
cd skills/japan-stock-analysis
env/bin/pytest tests/
```

すべてネットワーク不要で完走する（XBRL fixture は `tests/fixtures/` に同梱）。約 3 秒で全件 PASS する想定。

実装変更時は必ずローカル pytest を通してから commit すること。CI は現状未設定（[README §テスト](skills/japan-stock-analysis/README.md) に将来構想あり）。

## 開発ルール

以下の開発ルールを必ず守ること。

- **`init_plan.md` を Single Source of Truth とする**: 設計判断は `init_plan.md` を最上位とし、各種 docs は plan を補強・詳細化する関係。`init_plan.md` と他 docs に矛盾が見つかったら `init_plan.md` を正として判断、必要なら ↓ で許可を取って修正する
- **`init_plan.md` の変更には開発者の許可が必要**: 設計の根幹に影響するため、変更前に必ず開発者に確認を取ること
- **Markdown 内の AI 指示コメントを確認する**: Markdown ファイル内に HTML コメント（`<!-- ... -->`）がある場合、AI 向けの編集指示が含まれている可能性がある。指示に従うこと。先頭行（1 行目）の AI 指示はファイル全体に適用されるルールであるため、編集箇所に関わらず必ず確認すること。先頭行以外は関連箇所の編集時のみ確認すればよい。AI 指示コメントには 2 種類ある:
  - `<!-- AI instruction: ... -->`: 対応完了後にコメントを削除する
  - `<!-- AI instruction (pinned): ... -->`: 対応後もコメントを削除してはならない（永続的なルール）
- **実装前に関連ドキュメントを読む（必須）**: 「設計ドキュメント」セクションの該当箇所を読むことは実装の前提条件である。読まずに実装・修正を開始してはならない
- **`pre-research/` は凍結。修正してはならない**: 設計検証の証跡。実装ロジックは `skills/japan-stock-analysis/scripts/` 側にあるので、変更はこちらに対して行う
- **バグは `bugs/`、改善は `enhancements/` に記録する**: 詳細は「バグ管理」「改善管理」セクションを参照
- **commit 方針**: Conventional Commits 形式（`feat:` / `fix:` / `docs:` / `refactor:` / `test:` / `chore:`）。Phase 単位や論理単位で分けてコミットすること。`git add .` や `git add -A` は禁止、個別ファイルを指定する。コミットメッセージ本文は英語、件名も英語推奨。`git commit` と `git push` はユーザー指示があるときのみ実行する
- **secret.json は絶対に commit しない**: EDINET API キーを含む。`skills/japan-stock-analysis/.gitignore` および ルート `.gitignore` で除外済み。新規ファイル追加時は `git status` で意図しないファイルが含まれていないか必ず確認
