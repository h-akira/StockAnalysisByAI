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
├── tmp/                       # 今後見返すかもしれない作業ファイル（tmp/README.md 参照）
├── old/                       # 説明済みや古い認識のアーカイブ（old/README.md 参照）
└── manual_test*/              # 手動テスト用 (Skill コピー、history.md 等。連番 manual_test_NN/ 含め gitignore 済)
```

**サブモジュールは無い。** ルートの `references/` は EDINET 公式仕様 PDF/XLSX の置き場であり設計ドキュメントではない。`tmp/` と `old/` は AI が通常作業時には参照しないアーカイブ領域。

## 設計ドキュメント（Single Source of Truth）

本プロジェクトの設計の正は以下に集約されている。実装着手前に必ず関連箇所を読むこと。
**まず [architecture.md](architecture.md) を読んで全体像を掴むこと。**

| ファイル | 責務 |
|---------|------|
| `architecture.md` | **現行アーキテクチャの正**。Mermaid 図つきの入口。`init_plan.md` を上書きする（init_plan は不可侵なので設計の進化は本ファイルに集約） |
| `init_plan.md` | **初期計画の SSoT（不可侵・凍結）**。全体設計、ディレクトリ構成、キャッシュポリシー、Phase 計画と完了条件、リスク管理。設計の経緯の参照用。現行の正は `architecture.md` |
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

### 設計思想: 会社差は AI で吸収する（コード固定化に走らない）

本 Skill は **AI 介在型 Agent Skill** である。日本株は会社・業種・会計基準（IFRS/JGAAP）・開示年度に
よって XBRL の要素・コンテキスト・値の基準が大きく異なる。この揺れを**コードの決定的アルゴリズムだけで
吸収しようとしない**。決定的に書けるのはホワイトリスト（`xbrl_extract.py` の `PATH_A/B_ITEMS`）等の
安定部分に限り、会社差で揺れる判断は **SKILL.md の手順・ナレッジ（`docs/`）を通じて AI に委ねる**のが
本プロジェクトの基本方針。

実装・修正にあたって必ず意識すること:

- **コードでの改善にこだわらない**。バグ/改善の対処を検討するとき、コード（`scripts/`）に閾値や分岐を
  足す前に、「SKILL.md の文面・`docs/` のナレッジを修正して AI に判断させる方が会社差に強くないか」を
  必ず検討する。固定閾値・固定マッピングは特定銘柄では正しくても他社でデグレ（誤警報・誤判定）を生む。
- **コードで警告/検証を入れる場合は会社差に対して保守的に**。1 社の観察から閾値を決めると他社で誤発火
  する。赤字・ゼロ近傍・基準切替・希薄化・分割の有無など、会社ごとに違う条件で誤検知しないよう、
  発火条件は十分に限定し、拾いきれないケースは SKILL.md 側の AI 判断でカバーする二層構成を基本とする。
- **参照・テスト・検証は複数社で行うことが望ましい**。`manual_test_*/` の手動テストや実機確認は、
  東京ガス（9531・JGAAP）だけでなく、トヨタ（7203・IFRS）、ソニー（6758）、銀行（8306）等、
  会計基準・業種の異なる複数銘柄で確認する。単一銘柄での「動いた」は一般化の根拠にならない。
  pytest の fixture も可能な範囲で複数社の XBRL を用意し、会社差に対する回帰を検出できるようにする。
- この方針は [tmp/QA_skill_invocation.md](tmp/QA_skill_invocation.md) の AI 介在前提や
  [SKILL.md](skills/japan-stock-analysis/SKILL.md) §6（エスカレーション）と一貫する。

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

## 手動テスト (`manual_test_*/`)

`manual_test_*/`（`manual_test_01/`, `manual_test_02/`, ...）は、**人間が別セッションで Skill を
実機実行して挙動を確認するための領域**。連番で 1 テスト 1 ディレクトリ。すべて gitignore 済
（ルート `.gitignore` の `manual_test_*/`）。AI が通常の実装作業で参照する必要はない。

### 基本方針: 「clone されて使われる直後」を再現する

この領域は、**利用者が Skill を `~/.claude/skills/` 等にコピーした直後のクリーンな状態**を模す。
つまり配布物に含まれないものは原則「無い」状態から始める:

- **venv（`env/`）は含めない**。利用者は自分で `python -m venv env && env/bin/pip install -r
  requirements.txt` する。手動テストでもその手順から始めるのが実態に忠実。AI が先回りで venv を
  作らない（作ると「セットアップ込みで動くか」の検証にならない）。
- **`derived/` `mappings/` `split_adjust/` `prices/` `xbrl/` のキャッシュは空から始める**。
  これらは analyze 実行で生成される銘柄固有の派生物。前テストの結果を残すと検証が汚染される。
- **pytest はネットワーク不要・fixture 同梱で完走する**ので、手動テスト環境でも venv さえ作れば
  `env/bin/pytest tests/` がそのまま通る（約 3 秒〜、117 件想定）。

### 例外: bootstrap キャッシュ（銘柄非依存）は使い回してよい

唯一の例外が **bootstrap で取得する重いキャッシュ**。取得に時間がかかり（10 年分 documents で
~40 分・約 600MB）、かつ**銘柄に依存しない公開情報のスナップショット**なので、テスト間でコピーして
使い回してよい:

- `cache/documents/`（全営業日の documents.json、~2,600 ファイル）
- `cache/company_map.csv`（EDINET 企業マスタ）

これらだけを既存の `manual_test_*/.claude/skills/japan-stock-analysis/cache/` からコピーし、
残りの cache サブディレクトリは空で用意する。キャッシュポリシーの正は `init_plan.md` §3.5。

## 開発ルール

以下の開発ルールを必ず守ること。

- **`architecture.md` を現行設計の正とする**: 設計判断は `architecture.md` を最上位とする。各種 docs は
  これを補強・詳細化する関係。`architecture.md` と他 docs に矛盾が見つかったら `architecture.md` を正として
  判断する。設計が進化したら（開発者の合意のうえで）`architecture.md` を更新する
- **`init_plan.md` は不可侵（凍結）**: 初期計画の記録であり**書き換えない**。設計の経緯の参照用として残す。
  init_plan.md と現行設計が食い違う場合は `architecture.md` を正とし、上書き内容は `architecture.md`
  （または別の設計改訂ノート）に記す。init_plan.md 本体には手を入れない
- **Markdown 内の AI 指示コメントを確認する**: Markdown ファイル内に HTML コメント（`<!-- ... -->`）がある場合、AI 向けの編集指示が含まれている可能性がある。指示に従うこと。先頭行（1 行目）の AI 指示はファイル全体に適用されるルールであるため、編集箇所に関わらず必ず確認すること。先頭行以外は関連箇所の編集時のみ確認すればよい。AI 指示コメントには 2 種類ある:
  - `<!-- AI instruction: ... -->`: 対応完了後にコメントを削除する
  - `<!-- AI instruction (pinned): ... -->`: 対応後もコメントを削除してはならない（永続的なルール）
- **実装前に関連ドキュメントを読む（必須）**: 「設計ドキュメント」セクションの該当箇所を読むことは実装の前提条件である。読まずに実装・修正を開始してはならない
- **`pre-research/` は凍結。修正してはならない**: 設計検証の証跡。実装ロジックは `skills/japan-stock-analysis/scripts/` 側にあるので、変更はこちらに対して行う
- **バグは `bugs/`、改善は `enhancements/` に記録する**: 詳細は「バグ管理」「改善管理」セクションを参照
- **commit 方針**: Conventional Commits 形式（`feat:` / `fix:` / `docs:` / `refactor:` / `test:` / `chore:`）。Phase 単位や論理単位で分けてコミットすること。`git add .` や `git add -A` は禁止、個別ファイルを指定する。コミットメッセージ本文は英語、件名も英語推奨。`git commit` と `git push` はユーザー指示があるときのみ実行する
- **secret.json は絶対に commit しない**: EDINET API キーを含む。`skills/japan-stock-analysis/.gitignore` および ルート `.gitignore` で除外済み。新規ファイル追加時は `git status` で意図しないファイルが含まれていないか必ず確認
