# japan-stock-analysis Skill

日本株（4桁証券コード）の個別分析を Claude Code から実行するための Agent Skill です。

> **このファイルは開発リポジトリ用の説明**です。Skill 配布物としてはこの README は
> 必須ではありません。Skill 本体の利用方法は [SKILL.md](SKILL.md) を参照してください。
>
> 同一リポジトリ内に開発過程の設計資料 ([plan.md](../../plan.md) や
> [pre-research/](../../pre-research/)) があり、開発時はそれらを参照しますが、
> Skill 単体（`~/.claude/skills/japan-stock-analysis/` 等にコピー後）はそれらを
> 必要としません — 必要なナレッジは Skill 配下 [docs/](docs/) に独立した形で
> 入っています。

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

## テスト

```bash
# 仮想環境にテスト依存をインストール
env/bin/pip install pytest

# 全テスト実行（ネットワーク不要、約 3 秒で 90 件）
env/bin/pytest tests/
```

### テスト構成

| ファイル | 範囲 |
|---------|------|
| `test_paths.py` / `test_config.py` | パス解決、secret.json バリデーション |
| `test_bootstrap.py` | 日付生成、チャンク分割、`fetch_documents_json` の 429 リトライ |
| `test_doc_list.py` / `test_doc_list_windows.py` | キャッシュ済 documents の検索、銘柄の決算月ベースの提出ウィンドウ |
| `test_xbrl_extract.py` | merge ロジック + **fixture (S100VWVY / S100W19Q)** ベースの 9 項目抽出 |
| `test_split_adjust.py` / `test_metrics.py` | restated EPS マッピング、ratio 計算式 |
| `test_json_export.py` / `test_html_report.py` | スキーマ生成、Jinja2 レンダリング |
| `test_pipeline.py` | `cmd_analyze` end-to-end（fixture + yfinance モック） |
| `test_cache_admin.py` | clear のフラグ排他・`--confirm` 安全弁 |

### fixtures について

`tests/fixtures/` に Toyota FY2024 (S100VWVY.zip, 2.85MB) と Sony FY2024
(S100W19Q.zip, 1.16MB) の XBRL zip を **git 管理下**でコミットしている。
これらは EDINET から再取得できる不変ファイル（pre-research 検証済）。

### CI（将来検討）

現状は **ローカル `pytest` のみ**。テストは全てネットワーク不要で動くので、
将来 CI を入れる場合は最小構成として:

```yaml
# .github/workflows/test.yml の雛形（実装時に有効化）
name: tests
on: [push, pull_request]
jobs:
  pytest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -r skills/japan-stock-analysis/requirements.txt pytest
      - run: pytest skills/japan-stock-analysis/tests/
```

CI 採用は Skill が他者と共同開発に入る段階で検討する。それまでは
push 前に `env/bin/pytest tests/` を手動実行で十分。

## 将来の課題 (Future Work)

### 銀行業の CF 三区分集計

銀行業の連結 XBRL では `CashFlowsFromUsedInOperatingActivities` 等の
**CF 三区分集計値が単独要素として存在しない**ことが MUFG (8306) の検証で
判明 (Phase P8)。明細項目 `*OpeCF/*InvCF/*FinCF` は数十個あるが、その合算
ロジックが銀行ごとに違うため標準化が難しい。

現状は SKILL.md §6.3 の `unresolved[]` パターンで NaN 扱いとしている。
将来の改善余地:
1. 銀行業向けに明細を合算するロジックを `xbrl_extract.py` に組み込む
2. 銀行業の `mapping_resolver` が `aggregate: [element1, element2, ...]` という
   合算指示を受けられる仕様を追加 (現状は単一 element のみ)

### PBR の分割補正

`SharesOutstanding` の restated 形式が `SummaryOfBusinessResults` に
存在しないため、株式分割をまたぐ期の PBR は filing-time 基準の生
SharesOutstanding を使う (P4 / P3.5 verification_results §Step7)。
yfinance.Ticker.splits の累積比率で除算する手法で補正可能だが、
EPS と同様に「期中平均株式数」を考慮しない近似値になる。本実装では
未対応。

### 多銘柄スクリーニング

「PER<15 かつ ROE>10%」のような条件で全上場銘柄から候補抽出する用途は
plan §1 の非ゴール。需要が出てきたら別 Skill `japan-stock-screening`
として切り出すのが筋。
