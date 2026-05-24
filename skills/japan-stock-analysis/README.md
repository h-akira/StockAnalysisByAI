# japan-stock-analysis Skill

日本株（4桁証券コード）の個別分析を Claude Code から実行するための Agent Skill です。

> **このファイルは開発リポジトリ用の説明**です。Skill 配布物としてはこの README は
> 必須ではありません。Skill 本体の利用方法は [SKILL.md](SKILL.md) を参照してください。
>
> 同一リポジトリ内に開発過程の設計資料 ([init_plan.md](../../init_plan.md) や
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

本 Skill は段階的に実装中です。各 Phase の進捗は [init_plan.md §5](../../init_plan.md) を参照。

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

このセクションは将来の改善作業の起点となるよう、Phase P1〜P9 で確認した
**全ての** 未対応事項を体系的に整理する。優先度は「実用への影響度」順:
P0 (現在ある銘柄で誤った数値が出る) > P1 (NaN/欠落で済むが対応すれば
精度向上) > P2 (新機能・スコープ拡張)。

---

### 最大の課題: 会社・業種・基準による XBRL 差異

P9 の 5 銘柄実機検証で明確になった通り、本 Skill の **最大の運用負荷は
「銘柄ごとに XBRL 要素名と構造が違う」こと**。現状は2 層構造で対応:

1. **ホワイトリスト** ([scripts/xbrl_extract.py](scripts/xbrl_extract.py)):
   トヨタ・ソニーで実証された IFRS 連結製造業の典型パターン
2. **LLM エスカレーション** ([SKILL.md §6](SKILL.md)):
   ホワイトリスト未解決 → 候補ペイロード生成 → Claude 判定 → `cache/mappings/{sec_code}.json` 永続化

P9 検証で、5 銘柄のうち **3 銘柄 (8306/9432/4502) が LLM エスカレーションを
必要とした** (60%)。この比率は業種が広がるほど上がる見込み。以下、軸別の
具体的課題:

#### A. ホワイトリスト不足 (P0)

P9 で発見:

| 項目 | 不足要素 | 影響銘柄 | 提案する追加 |
|------|---------|----------|-------------|
| `NetSales` | `jpigp_cor:RevenueIFRS` (IFRS 標準) | 4502 武田 | Path A 候補に追加 |
| `NetSales` | `ISSUER:OperatingRevenuesIFRS` (通信業) | 9432 NTT | 業種別フォールバック |
| `InterestBearingDebt` | `jpigp_cor:BondsAndBorrowingsCLIFRS + NCLIFRS` (薬品/一般 IFRS) | 4502 武田 | 新パターン (Pattern 3) として追加 |

**影響**: 上記を whitelist に入れれば武田は LLM 介入不要になり、Skill の
"out-of-the-box success rate" が大幅に上がる。**最も投資対効果が高い改善項目**。

#### B. `extra_mappings` の単一要素縛り (P1)

現状 mapping_resolver は **1 項目 = 1 要素** しか扱えない。
銀行業や薬品の IFRS では合算が必要なケースが多い:

- **武田 IBD**: `BondsAndBorrowingsCLIFRS` + `BondsAndBorrowingsNCLIFRS`
- **銀行 IBD (本来)**: `Deposits` + `NegotiableCertificatesOfDeposit` + 他
- **NTT IBD (本来)**: `LongTermDebt` + `ShortTermDebt` + lease liabilities

提案する仕様拡張:
```json
{
  "InterestBearingDebt": {
    "aggregate": [
      {"element": "jpigp_cor:BondsAndBorrowingsCLIFRS", "context": "CurrentYearInstant"},
      {"element": "jpigp_cor:BondsAndBorrowingsNCLIFRS", "context": "CurrentYearInstant"}
    ],
    "rationale": "..."
  }
}
```

`xbrl_extract._apply_extra_mappings` で `aggregate` キーがあれば各要素を
get_fact して整数加算するパスを追加するだけ。

#### C. 銀行業の CF 三区分集計 (P1)

[docs/xbrl_variation_knowledge.md §8.1](docs/xbrl_variation_knowledge.md) と
[docs/p9_smoke_results.md](docs/p9_smoke_results.md) 参照。

銀行業の連結 XBRL では `CashFlowsFromUsedInOperatingActivities` 等の **CF
三区分集計値が単独要素として存在しない**。明細項目 `*OpeCF/*InvCF/*FinCF`
は数十個あるが、構成が銀行ごとに違う。

現状は SKILL.md §6.3 の `unresolved[]` パターンで NaN 扱い (MUFG 検証)。
将来の対応案 (B の `aggregate` 仕様があれば実現可能):

1. MUFG / 三井住友 FG / みずほ FG の 3 行の `*OpeCF` 明細を実機で並べ、
   共通する 5〜10 個の core 要素を選定して `aggregate` マッピング化
2. 不足分があれば warnings に「approximate, X% items aggregated」と注記

#### D. JGAAP 銀行業の Basic EPS (P0)

[scripts/split_adjust.py](scripts/split_adjust.py) は restated EPS を
`BasicEarningsLossPerShareIFRSSummaryOfBusinessResults` (IFRS) 一択で
検索しているため、JGAAP 銀行 (MUFG) では一切ヒットせず PER が NaN になる。

提案:

- `extract_restated_eps_from_zip` で IFRS 名前空間を probe して空なら
  JGAAP 名前空間 (`BasicEarningsLossPerShareSummaryOfBusinessResults`、
  `IFRS` suffix なし) もフォールバック
- 失敗時のみ Diluted EPS Summary を採用 (MUFG 検証で 8306 が現に
  Diluted のみ提供しているのと整合)

これだけで MUFG の PER が出るようになる。実装コストは小。

#### E. issuer-specific namespace の運用

P9 検証で、9432 NTT と 6758 Sony で `ISSUER:` プレフィックスの企業独自
要素を採用する必要があった。本実装では既にサポートされているが、判定
ロジックは Claude 任せ。

将来:

- よく使われる issuer-specific element の業界横断マッピング (例:
  `OperatingRevenuesIFRS` を通信業 3 社で確認すれば NTT / KDDI /
  ソフトバンク を whitelist 化できる)
- 業種別 mapping プリセット (`cache/mappings/_industry_telecom.json`
  のようなテンプレ) — 新規 sec_code 投入時、業種ヒットで自動マッピング

---

### 株式分割補正の積み残し (P1)

#### F. PBR の分割未補正

`SharesOutstanding` の restated 形式が `SummaryOfBusinessResults` に
存在しないため、株式分割をまたぐ期の PBR は filing-time 基準の生
SharesOutstanding を使う ([P3.5 step7 verification](../../pre-research/edinet/verification_results.md))。

実装案 (中難易度): yfinance.Ticker.splits の累積比率で SharesOutstanding を
post-split basis に rebase。EPS と同様に「期中平均株式数」を考慮しない
近似だが、PBR の桁ズレ (Sony FY2022 で実測 0.42 → 真値約 1.5) は解消する。

#### G. 株式分割補正の 5 年超期間

[scripts/split_adjust.py](scripts/split_adjust.py) は最新報告書の
`Prior*YearDuration` (5 期分) しか見ない。10 年前の期は restated EPS
不取得 → PER NaN + warning。

対応案 (低難易度): 過去の年次報告書もループで読んで、報告書ごとの
`Prior*YearDuration` をマージすれば 10〜15 年前までカバー可能。
ただし XBRL の繰り返しダウンロードと SubtotalDuration 計算が必要。

#### H. 期中平均株式数の正確な反映

Step 7 で実証された通り、yfinance splits は **単純な分割比割り戻し** で
あり、自己株取得が活発な企業 (Sony 等) では実際の restated EPS と数 %
ずれる。本実装は restated EPS 方式を採用済みなので影響軽微だが、
スコープ外期間で yfinance フォールバックを採用する場合は注記必須。

---

### scripts レイヤの将来課題 (P1)

#### I. 月次決算 (4-6 月決算) のラベル誤り

[scripts/html_report.py:_fiscal_labels](scripts/html_report.py) は
"period_end の月 <=6 → year - 1、そうでなければ year" の単純ルール。
- 3 月 / 12 月決算 (multiple cases): OK
- **5 月決算 (例: 2876 ニッスイ) → FY が 1 年ズレる可能性**

修正案: `company_map.csv` の `fiscal_month` を引いて FY を判定する。

#### J. 会計基準の年度間切替

同一銘柄で IFRS → JGAAP (またはその逆) に切り替わると、数値の連続性が
崩れる (whitelist の選択候補が変わる)。本実装では年度ごとに独立に
ホワイトリストを走らせるので **値は取れるが時系列としての比較性が
損なわれる**。warnings に切替が起きた期を明示する仕掛けがほしい。

#### K. 9432 NTT IBD のような近似マッピング

P9 で 9432 NTT の IBD は `ISSUER:LongTermDebtIFRSNCLIFRS` 単独で
マッピングしたが、本来は短期借入 + lease liabilities も含めるべき。
Skill 用途として近似値で十分との判断だが、JSON 出力に
`approximation: true` フィールドを設けて警告するのが筋。

---

### Skill ライフサイクル系の課題 (P2)

#### L. company_map.csv の鮮度

`cache/company_map.csv` は手動 `refresh-company-map` でしか更新されない。
新規上場・上場廃止が即座に反映されないため、初出の sec_code 入力時に
古い情報で誤判定する可能性。init_plan.md §3.6 では「7 日」とあったが未実装。

実装案: `cache_admin info` で `company_map.mtime` が 7 日以上前なら
warnings に出す。または pipeline analyze 冒頭で auto-refresh。

#### M. yfinance 価格キャッシュの TTL

[scripts/stock_price.py](scripts/stock_price.py) は 1 日 TTL だが、
mtime ベースで荒い。期末価格だけ別途キャッシュして TTL を 7 日に
緩める方が API 親切。

#### N. CI

[README §テスト](#テスト) 通り、現状ローカル pytest のみ。Skill が
他者と共同開発に入る段階で GitHub Actions を有効化。雛形は記載済み。

---

### スコープ外 = 別 Skill として切り出す (P2)

#### O. 多銘柄スクリーニング

「PER<15 かつ ROE>10%」のような条件で全上場銘柄から候補抽出する用途は
init_plan.md §1 の非ゴール。本 Skill の bootstrap キャッシュ (documents +
xbrl) は再利用できるので、別 Skill `japan-stock-screening` として
切り出すのが筋。

#### P. 株価チャート (init_plan.md §5 P10)

日足/週足/月足の株価チャートを HTML レポートに統合する。yfinance は
取得可能なのでデータ層は問題なし。Plotly の range selector を組み込めば
時間軸切替も簡単。`scripts/chart_price.py` のスタブは P1 で作成済み
([scripts/chart_price.py](scripts/chart_price.py))。

#### Q. セクター・業種別ベンチマーク

「同業他社平均 PER との比較」のような分析は plan 非ゴール。実装するなら
P5 の JSON スキーマに `peers: []` フィールドを追加し、ベンチマーク
ロジックを別 Skill (`japan-sector-benchmark` 等) として切り出す。

#### R. リアルタイム株価・信用残・空売り

EDINET の枠を超えるので別データソース (J-Quants 等) が必要。pre-research
段階で「J-Quants は古い・期間短いので不採用」と判断 ([init_plan.md §1](../../init_plan.md))。

---

### 関連参照

- [docs/p9_smoke_results.md](docs/p9_smoke_results.md): P9 検証の生データと改善余地
- [docs/xbrl_variation_knowledge.md](docs/xbrl_variation_knowledge.md): 業種別マッピングのナレッジ (拡張の起点)
- [docs/json_schema.md](docs/json_schema.md): data_*.json の v1.0 仕様 (拡張時の互換性管理)
- [SKILL.md](SKILL.md): Claude が読む実行手順書
