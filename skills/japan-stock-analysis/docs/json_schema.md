# `data_{sec_code}.json` 出力スキーマ

`pipeline analyze` 完了時に CWD に書き出される、銘柄単位の機械可読データファイルの仕様。
このファイルは Claude や他ツールが Skill の出力を二次利用するときの **公式インターフェース**。

- ファイル名: `data_{sec_code}.json`
- 配置: 実行時の CWD（init_plan.md §3.4 / §4.3）
- エンコーディング: UTF-8
- インデント: 2 スペース（人間も読みやすく）
- バージョン: `schema_version` フィールドで明示（後方互換が壊れたら bump）

## トップレベル構造

```json
{
  "schema_version": "1.0",
  "sec_code": "6758",
  "company_name": "ソニーグループ株式会社",
  "edinet_code": "E01777",
  "generated_at": "2026-05-22T15:00:00+00:00",
  "source_doc_ids": ["S100QZT6", "S100TS7P", "S100W19Q"],
  "split_adjust_source_doc_id": "S100W19Q",
  "fiscal_years": [
    {
      "period_end": "2023-03-31",
      "financials": { ... },
      "metrics": { ... }
    },
    ...
  ],
  "warnings": []
}
```

## フィールド定義

### トップレベル

| キー | 型 | 説明 |
|------|-----|------|
| `schema_version` | string | スキーマバージョン（"major.minor"）|
| `sec_code` | string | 4桁証券コード |
| `company_name` | string | 提出者名（company_map から） |
| `edinet_code` | string | EDINETコード |
| `generated_at` | string (ISO 8601 UTC) | この JSON を書き出した時刻 |
| `source_doc_ids` | string[] | 構築に使った有報の docID 配列（period_end 昇順） |
| `split_adjust_source_doc_id` | string \| null | restated EPS の出処となった最新 docID（null = 補正なし） |
| `fiscal_years` | object[] | 年度ごとの財務+指標。詳細は下記 |
| `warnings` | string[] | 補正できなかった期や yfinance 失敗等の警告メッセージ |

### `fiscal_years[i]`

| キー | 型 | 説明 |
|------|-----|------|
| `period_end` | string (YYYY-MM-DD) | 決算期末日 |
| `financials` | object | 9 項目 + FreeCF（下表） |
| `metrics` | object | 11 指標（下表） |

#### `financials` の中身（cache/derived/timeseries_{sec_code}.csv と同一）

| キー | 型 | 単位 | 取得元 |
|------|-----|------|-------|
| `NetSales` | number \| null | JPY | XBRL Path A 優先 |
| `OperatingIncome` | number \| null | JPY | XBRL Path A |
| `ProfitLoss` | number \| null | JPY | XBRL Path A |
| `EarningsPerShare` | number \| null | JPY/share | XBRL Path B（raw、最新報告書時点ではない） |
| `TotalAssets` | number \| null | JPY | XBRL Path A |
| `NetAssets` | number \| null | JPY | XBRL Path A（親会社株主帰属持分） |
| `InterestBearingDebt` | number \| null | JPY | XBRL Path A（複数要素の合算） |
| `OperatingCF` | number \| null | JPY | XBRL Path B |
| `InvestingCF` | number \| null | JPY | XBRL Path B |
| `FinancingCF` | number \| null | JPY | XBRL Path B |
| `SharesOutstanding` | number \| null | shares | XBRL Path A (FilingDateInstant) |
| `FreeCF` | number \| null | JPY | OperatingCF + InvestingCF |

#### `metrics` の中身（cache/derived/metrics_{sec_code}.csv と同一）

| キー | 型 | 単位 | 算出元 |
|------|-----|------|-------|
| `OperatingMargin` | number \| null | decimal (0.12 = 12%) | OperatingIncome / NetSales |
| `NetMargin` | number \| null | decimal | ProfitLoss / NetSales |
| `ROE` | number \| null | decimal | ProfitLoss / NetAssets |
| `EquityRatio` | number \| null | decimal | NetAssets / TotalAssets |
| `DERatio` | number \| null | decimal | InterestBearingDebt / NetAssets |
| `SalesGrowth` | number \| null | decimal | NetSales pct_change（初年度 null） |
| `ProfitGrowth` | number \| null | decimal | ProfitLoss pct_change（初年度 null） |
| `BPS` | number \| null | JPY/share | NetAssets / SharesOutstanding（**分割未補正**） |
| `StockPrice` | number \| null | JPY | yfinance の period_end 以前直近 Close |
| `EPSForPER` | number \| null | JPY/share | split_adjust が在ればそれ、無ければ raw EPS |
| `PER` | number \| null | 倍 | StockPrice / EPSForPER |
| `PBR` | number \| null | 倍 | StockPrice / BPS（**分割未補正**） |

## null の意味

- `financials.*` の null = XBRL から該当要素が取れなかった（業種・会計基準・銘柄独自要素のいずれか）
- `metrics.PER` の null = `EPSForPER` が null、または StockPrice が null（5年超 / yfinance 失敗 / --no-yfinance）
- `metrics.SalesGrowth` / `ProfitGrowth` は 初年度が常に null（前年データがないため）
- `metrics.PBR` の null = SharesOutstanding が 0 or null

## 警告（`warnings`）の例

```json
[
  "[6758] PER is NaN for periods outside the latest report's restated EPS coverage (5-year window): ['2020-03-31']. PBR also retains the unfixed share-count basis (see split_adjust caveat).",
  "[7203] yfinance failed: RuntimeError('yfinance returned no data for 7203.T'); valuation metrics will be NaN."
]
```

警告は **prefix `[sec_code]`** を付けて発生銘柄を明示。比較レポート時に複数銘柄分が混ざる前提。

## 既知の制約

- **PBR の分割補正は未実装**: 最新報告書の SummaryOfBusinessResults に restated SharesOutstanding が無いため、SharesOutstanding は raw（filing-time 基準）。`PBR` 列は分割をまたぐ期で歪む。init_plan.md §4.5 split_adjust 行に明記
- **5年超の期間**: restated EPS の射程外 → PER null + warning
- **会計基準混在**: 同一銘柄でも年度によって JGAAP↔IFRS が切り替わると financials の値が連続しない可能性あり

## バージョニング方針

- minor bump（1.0 → 1.1）: 既存フィールドを残してフィールド追加
- major bump（1.0 → 2.0）: 既存フィールド名・型・意味の変更（破壊的）
- 1.x の間は consumer 側が「未知のキーは無視」する前提で動かす
