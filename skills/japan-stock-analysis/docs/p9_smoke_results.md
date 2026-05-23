# P9 通し動作確認 結果

実施日: 2026-05-23
目的: plan.md §5 P9 の完了条件 (fresh環境で5銘柄の通し動作) を満たす。
スコープ: cache 全削除 → bootstrap → 5 銘柄分析 → 比較レポートまで。

## 対象銘柄 (業種・会計基準で多様性を確保)

| 銘柄 | 名称 | 業種 | 会計基準 | 期待される挙動 |
|------|------|------|---------|---------------|
| 7203 | トヨタ自動車 | 輸送用機器 | IFRS | ホワイトリスト完全ヒット (P3 で検証済) |
| 6758 | ソニーグループ | 電気機器 | IFRS | 株式分割銘柄、issuer-specific revenue (P4/P7 で検証済) |
| 8306 | 三菱UFJ FG | 銀行業 | JGAAP | LLM マッピング必須 (P8 で検証済) |
| 9432 | NTT | 情報・通信 | IFRS | NetSales/IBD は issuer-specific |
| 4502 | 武田薬品工業 | 医薬品 | IFRS | NetSales は jpigp_cor:RevenueIFRS (whitelist にない) |

## 実行ステップと結果

### Step 1: cache 全削除

```bash
$ ${CLAUDE_SKILL_DIR}/scripts/cache_admin.py clear --all --confirm
{"status": "success", "removed_count": 15}
```

cache/{company_map.csv, documents/, xbrl/, derived/, prices/, mappings/, split_adjust/} すべて 0 件に。

### Step 2: company_map 取得

```bash
$ ${CLAUDE_SKILL_DIR}/scripts/bootstrap.py refresh-company-map
{"status": "success", "raw_rows": 11315, "listed_entries": 3852}
```

### Step 3: 3 年分の全平日 documents bootstrap

```bash
$ ${CLAUDE_SKILL_DIR}/scripts/bootstrap.py fetch-documents --years 3 --sleep 1.0
```

| 項目 | 値 |
|------|-----|
| 対象期間 | 2023-05-24 〜 2026-05-22 |
| 対象平日数 | 783 |
| fetched | 783 |
| errors | 0 |
| 所要時間 | 約 13 分 (1秒間隔) |
| キャッシュサイズ | 186 MB |

EDINET API の明示的なレート制限は公式にないが、1 秒間隔で 783 リクエスト連続でも 429 ゼロ。

### Step 4: 5 銘柄 analyze

#### 7203 トヨタ
- `--years 3`: 即 success、warnings なし
- 5 銘柄のうち**唯一 LLM マッピング不要**(whitelist 完全ヒット)

#### 6758 ソニー
- `--years 3`: 即 success、warnings なし
- 株式分割 (2024-10) 後の Prior2YearDuration からの restated EPS が機能

#### 9432 NTT
- 1 回目: `needs_mapping`、unresolved = `[InterestBearingDebt, NetSales]`
- Claude 判定:
  - NetSales → `ISSUER:OperatingRevenuesIFRS` (13.7 兆円)
  - InterestBearingDebt → `ISSUER:LongTermDebtIFRSNCLIFRS` (7.19 兆円、近似)
- 2 回目: success、warnings = LLM マッピング使用注意

#### 4502 武田薬品
- 1 回目: `needs_mapping`、unresolved = `[InterestBearingDebt, NetSales]`
- Claude 判定:
  - NetSales → `jpigp_cor:RevenueIFRS` (4.58 兆円、IFRS 標準だが whitelist に無かった)
  - InterestBearingDebt → `unresolved[]` (`BondsAndBorrowingsCLIFRS` + `NCLIFRS` の2行加算が必要だが extra_mappings は単一要素のみ対応)
- 2 回目: success、warnings = LLM マッピング使用 + IBD 意図的 NaN

#### 8306 MUFG (P8 で検証済の手順を再現)
- 1 回目: `needs_mapping`、unresolved = `[CF三種, EarningsPerShare, InterestBearingDebt, NetSales, OperatingIncome]`
- Claude 判定:
  - NetSales → `jppfs_cor:OrdinaryIncomeBNK` (経常収益 13.6 兆円、BNK suffix 重要)
  - OperatingIncome → `jppfs_cor:OrdinaryIncome` (経常利益 2.67 兆円)
  - EPS → `jpcrp_cor:DilutedEarningsPerShareSummaryOfBusinessResults` (Basic は無い)
  - InterestBearingDebt → `jppfs_cor:DepositsLiabilitiesBNK` (預金 228 兆円)
  - CF 三種 → `unresolved[]` (XBRL に集計値なし)
- 2 回目: success、warnings = LLM マッピング + 5年超 PER NaN + CF 意図的 NaN

### Step 5: 5 銘柄比較レポート

```bash
$ ${CLAUDE_SKILL_DIR}/scripts/pipeline.py analyze --sec-code 7203 6758 8306 9432 4502 --years 3
```

success、`report_7203_6758_8306_9432_4502.html` (4.9 MB) 生成。

## FY2024 主要指標サマリー (数値の妥当性確認)

| 銘柄 | NetSales(兆) | ROE | OpMargin | PER | PBR |
|------|-------------|-----|----------|-----|-----|
| 7203 トヨタ | 48.04 | 13.26% | 9.98% | 7.28 | 1.15 |
| 6758 ソニー | 12.96 | 13.96% | 10.86% | 19.95 | 2.83 |
| 8306 MUFG | 13.63 | 8.94% | 19.59% | NaN | 1.12 |
| 9432 NTT | 13.70 | 9.78% | 12.04% | 12.10 | 1.28 |
| 4502 武田 | 4.58 | 1.56% | 7.48% | 64.56 | 1.01 |

各値はおおむね公開情報・市場感覚と整合 (MUFG PER NaN は restated EPS が IFRS 名前空間に存在せず、現状の `split_adjust` が JGAAP に未対応のため。設計上の制約として認識済み)。

## 出力ファイル一覧 (CWD = /tmp/2026-q2-analysis)

| ファイル | サイズ |
|---------|--------|
| data_7203.json | 3.4 KB |
| data_6758.json | 3.4 KB |
| data_8306.json | 3.8 KB |
| data_9432.json | 3.6 KB |
| data_4502.json | 3.6 KB |
| report_7203.html | 4.85 MB |
| report_6758.html | 4.85 MB |
| report_8306.html | 4.86 MB |
| report_9432.html | 4.85 MB |
| report_4502.html | 4.85 MB |
| report_7203_6758_8306_9432_4502.html | 4.91 MB (比較ビュー) |

## P9 完了条件の判定

plan §5 P9 完了条件: 「fresh環境で通し動作（bootstrapから分析まで）、5銘柄（IFRS製造業＋日本基準＋銀行業含む）でレポート生成成功」

- [x] fresh環境: cache_admin clear --all --confirm でゼロから
- [x] bootstrap from scratch: company_map + 3年分documents (783件) 取得
- [x] 5銘柄でレポート生成成功
- [x] IFRS製造業 (7203, 6758)、IFRS非製造業 (9432 通信, 4502 製薬)、日本基準銀行業 (8306) の3カテゴリをカバー
- [x] AI エスカレーションが3銘柄 (8306, 9432, 4502) で起動し、それぞれ正しいマッピングを Claude が判定して save → 再 analyze success

**判定: PASS**

## P9 で発見された改善余地 (将来の TODO)

1. **whitelist 拡張**: `jpigp_cor:RevenueIFRS` (4502 で必要、IFRS 標準) を Path A の NetSales 候補に追加すれば武田はマッピング不要に。同様に NTT 系の `OperatingRevenuesIFRS` も検討
2. **複数要素加算マッピング**: 4502 の `BondsAndBorrowingsCLIFRS + NCLIFRS` のように 2 要素加算が必要なケースが多い。`extra_mappings` に `aggregate: [el1, el2, ...]` 仕様を追加すれば対応可能 (README 「将来の課題」参照)
3. **MUFG PER NaN**: split_adjust の restated EPS は `BasicEarningsLossPerShareIFRSSummaryOfBusinessResults` (IFRS) しか見ない。JGAAP 銀行は `BasicEarningsLossPerShareSummaryOfBusinessResults` (IFRS なし) も候補にする必要あり

これらは P10 以降の改善項目として記録。Skill の現状機能で **plan §5 全 Phase の完了条件は満たす**。
