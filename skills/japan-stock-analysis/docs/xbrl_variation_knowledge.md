# XBRL 要素マッピングのナレッジ（Claude 向け）

このドキュメントは [SKILL.md §6](../SKILL.md) のエスカレーション手順で
Claude が読む参照資料。Skill 単体で自己完結するよう、必要なナレッジを
すべて本ファイル内に持たせている。

---

## 1. 何を判定するのか

`scripts/xbrl_extract.py` のホワイトリストには無い XBRL 要素を、9 つの財務項目
（NetSales / OperatingIncome / ProfitLoss / EarningsPerShare / TotalAssets /
NetAssets / InterestBearingDebt / OperatingCF / InvestingCF / FinancingCF /
SharesOutstanding）の **どれに対応させるか** を1対1で決める。

判定結果は `cache/mappings/{sec_code}.json` に永続化され、以降の analyze で
再利用される（AI 介入は初回のみ）。

---

## 2. XBRL 名前空間の意味

| 名前空間 | 意味 |
|---------|------|
| `jpigp_cor` | **IFRS 連結**（提出企業が IFRS を採用している場合） |
| `jppfs_cor` | **日本基準**（多くの場合は親会社単体だが、日本基準採用なら連結も） |
| `jpcrp_cor` | **開示府令タクソノミ**。`SummaryOfBusinessResults` 系（5期分まとめ）も含む |
| `jpcrp030000-asr_<EDINETコード>-000` | **企業独自の拡張要素**（issuer-specific、ISSUER エイリアスでアクセス） |

---

## 3. context の解釈

| context ID | 意味 |
|-----------|------|
| `CurrentYearDuration` | 当期、フロー項目（PL・CF） |
| `CurrentYearInstant` | 当期末、ストック項目（BS） |
| `Prior{N}YearDuration` | N 期前のフロー |
| `Prior{N}YearInstant` | N 期前のストック |
| `FilingDateInstant` | 報告書提出日時点（SharesOutstanding 等） |
| `*_Member` | セグメント・人別等の内訳（**抽出対象から外す**） |
| `*_NonConsolidatedMember` | 親会社単体（連結読みなら**外す**） |

抽出するときは原則 `CurrentYearDuration` / `CurrentYearInstant` の **`_Member` なし**を選ぶ。

---

## 4. 9 項目の既知の候補要素

| 項目 | 意味 | IFRS 候補 | 日本基準 候補 |
|------|-----|-----------|-------------|
| **NetSales** | 連結の主要収益（金融サービスを含む合計） | `SalesRevenuesIFRS`<br/>`SalesAndFinancialServicesRevenueIFRS`<br/>`jpigp_cor:NetSalesIFRS` | `jppfs_cor:NetSales`<br/>`jppfs_cor:OperatingRevenue1` |
| **OperatingIncome** | 本業の利益 | `jpigp_cor:OperatingProfitLossIFRS` | `jppfs_cor:OperatingIncome` |
| **ProfitLoss** | 親会社株主帰属 | `jpigp_cor:ProfitLossAttributableToOwnersOfParentIFRS` | `jppfs_cor:ProfitLossAttributableToOwnersOfParent` |
| **EarningsPerShare** | 1株あたり利益 | `jpcrp_cor:BasicEarningsLossPerShareIFRSSummaryOfBusinessResults`（Path B 経由） | 同様に Summary 経由 |
| **TotalAssets** | 連結合計 | `jpigp_cor:LiabilitiesAndEquityIFRS` | `jppfs_cor:Assets` |
| **NetAssets** | 親会社株主帰属 | `jpigp_cor:EquityAttributableToOwnersOfParentIFRS` | `jppfs_cor:NetAssets`（単体／連結の解釈に注意） |
| **InterestBearingDebt** | 利付負債合計（短期+長期） | `InterestBearingLiabilitiesCLIFRS` + `NCLIFRS`<br/>または `BorrowingsCLIFRS` + 関連 | `jppfs_cor:BondsPayable` 等の加算 |
| **OperatingCF** | キャッシュフロー（営業） | `*CashFlowsFromUsedInOperatingActivitiesIFRS*`<br/>または本体 CF 計算書 | `jppfs_cor:CashFlowsFromUsedInOperatingActivities` |
| **InvestingCF** | 同（投資） | （同上 Investing） | （同上） |
| **FinancingCF** | 同（財務） | （同上 Financing） | （同上） |
| **SharesOutstanding** | 期末発行済株式数 | `jpcrp_cor:NumberOfIssuedSharesAsOfFiscalYearEndIssuedSharesTotalNumberOfSharesEtc` (FilingDateInstant) | 同上 |

---

## 5. 業種別の追加考慮

「製造業 IFRS」以外で頻発する代替要素。**この表に該当しない場合**でも、候補ペイロード
（`mapping_escalation_<sec_code>.json`）の中から「**項目の意味に最も近い実在要素**」を
選び、`rationale` に判定根拠を必ず残す。

| 業種 | 追加要素 / マッピング指針 |
|------|--------------------------|
| **銀行** | `NetSales` → `OrdinaryIncome`（経常収益）が売上に相当。<br/>`OperatingIncome` → `OrdinaryProfit` または相当。<br/>関連: `Loans`、`Deposits` |
| **保険** | `NetSales` → `PremiumIncome`（保険料収入）または `OrdinaryRevenue`。<br/>関連: `PolicyReserves`（責任準備金） |
| **不動産** | `NetSales` → `RealEstateSalesIFRS` 等の独自要素。<br/>関連: `InventoriesRealEstateForSale` |
| **商社** | `NetSales` → `RevenueIFRS` または `OperatingRevenue` |
| **その他** | issuer-specific (`ISSUER:` prefix) に独自命名の収益要素がある場合は最優先候補 |

---

## 6. 判定時の優先順位（推奨ヒューリスティック）

1. **IFRS 連結優先**: 連結ベースの企業なら `jpigp_cor:*` を最優先
2. **業種固有が示唆される場合**: §5 の表が示唆するなら `jppfs_cor:OrdinaryIncome` 等を採用
3. **issuer-specific (ISSUER) は補助的**: 業種・基準で説明できない場合のみ（Sony の `SalesAndFinancialServicesRevenueIFRS` のような複合収益）
4. **`SummaryOfBusinessResults` 系は Path B**: EPS など本体に無いものはここから
5. **意味が複数候補で割れる場合**: 値の大きさ・単位（JPY/JPYPerShares/shares）が項目定義と整合する方を選ぶ

---

## 7. マッピング JSON フォーマット

Claude が組み立てて `mapping_resolver.py save --mapping-json <path>` に渡す JSON は以下:

```json
{
  "sec_code": "8306",
  "company_name": "株式会社三菱UFJフィナンシャル・グループ",
  "accounting_standard": "JGAAP",
  "industry_category": "bank",
  "mappings": {
    "NetSales": {
      "element": "jppfs_cor:OrdinaryIncome",
      "context": "CurrentYearDuration",
      "rationale": "銀行業では経常収益が売上に相当。§5 業種別ナレッジに従い選定。"
    },
    "OperatingIncome": {
      "element": "jppfs_cor:OrdinaryProfit",
      "context": "CurrentYearDuration",
      "rationale": "..."
    }
  },
  "unresolved": []
}
```

### フィールド説明

| キー | 型 | 説明 |
|------|-----|------|
| `sec_code` | string | 4桁証券コード |
| `company_name` | string | 提出者名（company_map から） |
| `accounting_standard` | "IFRS" \| "JGAAP" | 採用基準 |
| `industry_category` | string | 業種カテゴリ（bank/insurance/realestate/trading/general 等） |
| `mappings` | object | キーは 9 項目名、値は `{element, context, rationale}` |
| `mappings[item].element` | string | 採用した要素名（`prefix:localname` 形式、`ISSUER:`プレフィックス可） |
| `mappings[item].context` | string | コンテキスト ID（典型: `CurrentYearDuration` / `CurrentYearInstant`） |
| `mappings[item].rationale` | string | **必須**。判定根拠（業種ナレッジ参照 / サンプル値 / 候補比較 など） |
| `unresolved` | string[] | 判定不能だった項目（空配列推奨。残す場合は理由を `mappings[item].rationale` に書く） |

### 保存後の挙動

- `mapping_resolver.py save` は `cache/mappings/{sec_code}.json` に書き込み、
  `resolved_by: "llm"` と `resolved_at` を自動付加
- 次回 `pipeline analyze --sec-code <code>` 実行時、ホワイトリスト解決失敗の項目は
  この mapping を引いて埋まる
- 該当銘柄の `data_*.json` および HTML に「LLM 判定」フラグが warnings に乗る

---

## 8. 判定の品質を担保するための注意

1. **判定根拠は必ず残す**: `rationale` が空のマッピングは後で誰も検証できない
2. **値の大きさを確認**: 候補ペイロードの `sample_value` を見て、項目定義（売上は数百億〜数兆円、EPS は数百円〜数千円）と整合する方を選ぶ
3. **業種を間違えない**: company_map.csv の `industry` 列で銀行/保険/その他を確認
4. **会計基準も間違えない**: `jpigp_cor:` 要素が XBRL に存在するなら IFRS、無いなら JGAAP
5. **issuer-specific は最後**: 業種・基準で説明できる候補があるならそれを優先（issuer-specific は企業独自命名なので解釈にブレが出やすい）
6. **取れない項目は無理に当てない**: 候補に "意味的に正しい" 要素が無ければ `unresolved[]` に入れる
   （例: 銀行業の OperatingCF/InvestingCF/FinancingCF は集計値が単独要素として存在しない）。
   `unresolved[]` に入れた項目は **NaN として許容**され、再エスカレーションは発生しない。

### 8.1 既知の制限: 銀行業の CF 集計

銀行業の連結 XBRL では `CashFlowsFromUsedInOperatingActivities` 等の **CF 三区分集計値が
単独要素として存在しない** (明細項目 `*OpeCF/*InvCF/*FinCF` のみ)。
本実装では CF 三区分は `unresolved[]` に入れて NaN 扱いするのを推奨。
将来の改善案として「明細を合算するロジック」が考えられるが、明細の構成が銀行ごとに違うため
プロダクション実装は未提供。

---

## 9. 参考

- [scripts/xbrl_extract.py](../scripts/xbrl_extract.py): ホワイトリスト実装
- [SKILL.md §6](../SKILL.md): エスカレーション手順
