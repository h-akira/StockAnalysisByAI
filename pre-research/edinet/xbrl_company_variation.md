# 会社間の XBRL 表現差異と本実装方針の選択肢

> Step 3a で **トヨタ・ソニー** 2社の有報 XBRL を見比べて分かった「会社による違い」と、それを踏まえた本実装での選択肢を整理する。
> 本検証フェーズ（pre-research）の成果物として、**本実装時の判断材料**を残すのが目的。

---

## 1. 結論

**会社による違いはある**。しかも「**ホワイトリストで吸収できる小さい違い**」と「**事前列挙が困難な大きい違い**」の2種類に分かれる。

| 違いの種類 | 例 | 対処 |
|----------|-----|------|
| 小（既知の有限パターン） | 売上要素名のバリエーション、有利子負債の加算構成 | 優先順位付き候補リスト＋自動判定で吸収可能 |
| 大（事前列挙が困難） | 会計基準ごとの要素体系・業種固有勘定科目・企業独自拡張要素 | **AI による動的解決**が本実装での有力候補 |

本実装フェーズでは、**「Agent Skill で要素名マッピングを企業ごとに自動解決する」設計**を推奨する。本検証ではこの判断材料となるナレッジまで残す。

---

## 2. 実観測された差異（トヨタ vs ソニー、FY2024）

### 2.1 共通する点

両社ともIFRS連結・3月決算で、以下は完全に同じ:

- 名前空間の構成: `jpigp_cor`（IFRS）／`jpcrp_cor`（開示府令）／`jppfs_cor`（日本基準・親会社単体）／`jpcrp030000-asr_<EDINETコード>-000`（企業固有拡張）
- context 命名規則: `CurrentYearDuration` / `CurrentYearInstant` / `Prior{N}Year*`
- `*SummaryOfBusinessResults` 経路で当期純利益・総資産・純資産・EPS・CF三表が取れる
- 営業利益: `jpigp_cor:OperatingProfitLossIFRS@CurrentYearDuration`
- 当期純利益: `jpigp_cor:ProfitLossAttributableToOwnersOfParentIFRS@CurrentYearDuration`
- 純資産（親株主帰属）: `jpigp_cor:EquityAttributableToOwnersOfParentIFRS@CurrentYearInstant`
- 総資産: `jpigp_cor:LiabilitiesAndEquityIFRS@CurrentYearInstant`

### 2.2 違う点

#### 差異1: 売上の要素名

| 会社 | 要素名 | 値（FY2024） |
|------|--------|------------|
| トヨタ | `jpcrp030000-asr_E02144-000:SalesRevenuesIFRS` | 48.0兆 |
| ソニー | `jpcrp030000-asr_E01777-000:SalesAndFinancialServicesRevenueIFRS` | 13.0兆 |

両方とも**企業固有の拡張要素**で、要素名の URI に **EDINETコードが入る**。

ソニーは金融子会社を持つため独自に「商品売上＋金融サービス収益」の合算要素を定義している。
トヨタも金融子会社を持つが、要素名としては「Sales Revenues」を採用。

→ **同じ業界（製造業＋金融）でも企業ごとに要素名を独自設計**することがある。

#### 差異2: 有利子負債の構成

| 会社 | 加算要素 |
|------|---------|
| トヨタ | `jpigp_cor:InterestBearingLiabilitiesCLIFRS` + `NCLIFRS`（2要素加算） |
| ソニー | `jpigp_cor:BorrowingsCLIFRS` + `ISSUER:CurrentPortionOfLongTermDebtCLIFRS` + `ISSUER:LongTermDebt2NCLIFRS`（3要素加算） |

トヨタは「利付負債」をひとくくりにする要素名、ソニーは「短期借入」「長期負債の流動部分」「長期負債」と細分化。

→ **BS構成の見せ方そのものが企業ごとに違う**。IFRS は「合計だけ示せばよい」「内訳分けて示してもよい」と柔軟。

---

## 3. 「事前列挙が困難な大きい違い」のカテゴリ

二社検証では出会わなかったが、本実装で必ず遭遇する以下の差異:

### 3.1 会計基準の違い

| 基準 | 名前空間 | 採用企業の例 |
|------|---------|------------|
| 日本基準 | `jppfs_cor` | 任天堂、伊藤忠、多くの中小企業 |
| IFRS | `jpigp_cor` | トヨタ、ソニー、武田薬品、ホンダ |
| 米国基準 | `jpigp_cor`系の `*USGAAP` 等 | 一部の旧米国基準提出企業（縮小中） |

要素名体系が**根本的に違う**:
- 売上: `jpigp_cor:SalesRevenuesIFRS` vs `jppfs_cor:NetSales`
- 営業利益: `jpigp_cor:OperatingProfitLossIFRS` vs `jppfs_cor:OperatingIncome`
- 純利益: `jpigp_cor:ProfitLossAttributableToOwnersOfParentIFRS` vs `jppfs_cor:ProfitLoss`

「フォールバック候補」として両方並べる現行戦略でも基本ケースはカバーできるが、業種固有要素まで広げると指数的に増える。

### 3.2 業種固有勘定科目

製造業の前提では存在しない概念が登場:

| 業種 | 主要勘定科目（例） |
|------|------------------|
| 銀行 | 貸出金、預金、コールローン、有価証券、貸倒引当金 |
| 保険 | 責任準備金、支払備金、運用資産、保険料 |
| 不動産 | 販売用不動産、賃貸等不動産、固定資産税 |
| 商社 | 関係会社株式、棚卸資産、為替差損益 |

「総資産」「純資産」のような汎用項目は共通だが、**事業の本質を理解するための指標は業種固有**。

### 3.3 企業独自の拡張要素

`jpcrp030000-asr_<EDINETコード>-000` 名前空間は**企業が自由に独自要素を定義**できる。

例:
- ソニー: `SalesAndFinancialServicesRevenueIFRS`（金融セグメント込み）
- トヨタ: `SalesRevenuesIFRS`、`OperatingRevenuesIFRSKeyFinancialData` 等多数
- 銀行各社: 業務粗利益や経常収益などの独自定義

→ **EDINETタクソノミ仕様では網羅できない**。XBRLを見るまで何があるか分からない。

### 3.4 同名要素の意味揺れ

`jpcrp_cor:NetAssetsSummaryOfBusinessResults` という同じ要素名でも、context によって意味が変わる:

- トヨタ: `_NonConsolidatedMember` 付きで**親会社単体の純資産**が入る
- ソニー: 同要素は使わず、`EquityAttributableToOwnersOfParentIFRSSummaryOfBusinessResults` を使用

→ context まで含めて「何を意味するか」を判定する必要がある。

---

## 4. 本実装での対処方針

### 4.1 案A: ホワイトリスト方式の継続・拡張

**やること**: 業種別・会計基準別の要素名ホワイトリストをコードで管理。

**得意なこと**:
- TOPIX100クラスの大企業は、業種別パターンを揃えればほぼカバーできる
- 動作が決定的（同じ入力→同じ出力）

**苦手なこと**:
- 新業種・新企業に出会うたびに XBRL を覗いて手動で追加する作業が発生
- 企業独自要素は **企業ごとの個別対応**が必要
- 11,000社規模の全社対応は現実的でない

### 4.2 案B: AI（LLM）による動的解決 ★推奨

**やること**: 新企業の XBRL から要素名一覧と抜粋値を LLM に渡し、「この企業の売上はどの要素か」を判定させる。判定結果は企業ごとにキャッシュ。

**得意なこと**:
- 業種・会計基準・企業独自要素にも柔軟に対応
- 「`SalesAndFinancialServicesRevenue` は売上の一種」のような**意味ベースの判定**が可能
- ホワイトリストのメンテが不要

**苦手なこと**:
- LLM のレスポンスが非決定的になりうる（キャッシュとバリデーションで吸収）
- 推論コスト（ただし一度判定すればキャッシュできるので、初回コストのみ）
- 検証時に「正しさ」を担保する仕組みが別途必要

### 4.3 案C: AI＋ホワイトリストのハイブリッド

**やること**:
1. **典型パターン**（大企業の業種別ホワイトリスト）でまず試す
2. ヒットしなければ **LLM 判定**にフォールバック
3. 判定結果は **企業ごとの設定ファイル**として永続化

**メリット**:
- 既知の大企業は決定的・高速
- 未知の企業は AI で自動対応
- 段階的に「設定ファイル化」が進む

これが現実解として最有力候補。

### 4.4 LLM 判定で渡すべき情報（ナレッジ）

本実装で LLM を呼ぶときに、プロンプトに含めるべき**ナレッジ**:

#### 4.4.1 名前空間の意味
```
jpigp_cor   → IFRS連結（提出企業がIFRSを採用している場合）
jppfs_cor   → 日本基準（多くの場合は親会社単体だが、日本基準採用なら連結も）
jpcrp_cor   → 開示府令タクソノミ。SummaryOfBusinessResults 系（5期分まとめ）
jpcrp030000-asr_<EDINETコード>-000 → 企業独自の拡張要素
```

#### 4.4.2 context の解釈ルール
```
CurrentYearDuration  → 当期、フロー項目（PL・CF）
CurrentYearInstant   → 当期末、ストック項目（BS）
Prior{N}Year*        → N期前
*_Member             → セグメント・人別等の内訳
*_NonConsolidatedMember → 親会社単体
```

抽出するときは原則 `CurrentYearDuration` / `CurrentYearInstant` の **`_Member` なし**を選ぶ。

#### 4.4.3 9項目の意味と既知の候補要素名

| 項目 | 意味 | 既知の候補（IFRS） | 既知の候補（日本基準） |
|------|-----|------------------|---------------------|
| 売上高 | 連結の主要収益（金融サービスを含む合計） | `SalesRevenuesIFRS`<br/>`SalesAndFinancialServicesRevenueIFRS`<br/>`NetSalesIFRS` | `jppfs_cor:NetSales`<br/>`jppfs_cor:OperatingRevenue1` |
| 営業利益 | 本業の利益 | `jpigp_cor:OperatingProfitLossIFRS` | `jppfs_cor:OperatingIncome` |
| 当期純利益 | 親会社株主帰属 | `jpigp_cor:ProfitLossAttributableToOwnersOfParentIFRS` | `jppfs_cor:ProfitLossAttributableToOwnersOfParent` |
| EPS | 1株あたり利益 | `jpcrp_cor:BasicEarningsLossPerShareIFRSSummaryOfBusinessResults`（経路B推奨） | 同様にSummary経路 |
| 総資産 | 連結合計 | `jpigp_cor:LiabilitiesAndEquityIFRS` | `jppfs_cor:Assets` |
| 純資産 | 親会社株主帰属 | `jpigp_cor:EquityAttributableToOwnersOfParentIFRS` | `jppfs_cor:NetAssets`（注: 単体／連結の解釈に注意） |
| 有利子負債 | 利付負債合計（短期+長期） | `InterestBearingLiabilitiesCLIFRS` + `NCLIFRS`<br/>または `BorrowingsCLIFRS` + 関連 | `jppfs_cor:BondsPayable` 等の加算 |
| 営業CF | キャッシュフロー（営業） | `*CashFlowsFromUsedInOperatingActivitiesIFRS*`<br/>または本体CF計算書 | `jppfs_cor:CashFlowsFromUsedInOperatingActivities` |
| 投資CF | 同（投資） | （同上 Investing） | （同上） |
| 財務CF | 同（財務） | （同上 Financing） | （同上） |

#### 4.4.4 業種別の追加考慮（本実装で蓄積していく）

| 業種 | 追加で意識すべき要素 |
|------|------------------|
| 銀行 | `OrdinaryIncome`（経常収益）が売上に相当。`Loans` 関連、`Deposits` 関連 |
| 保険 | `PremiumIncome`（保険料収入）が売上に相当。`PolicyReserves`（責任準備金） |
| 不動産 | 売上は `RealEstateSalesIFRS` 等の独自要素。`InventoriesRealEstateForSale` |
| 商社 | 売上は `RevenueIFRS` または `OperatingRevenue` |

---

## 5. 検証フェーズでのスコープ判断

### このフェーズで完了したこと

- [x] 2社（トヨタ・ソニー）で 9項目を抽出する仕組みを実証
- [x] **ホワイトリスト＋優先順位付き候補リスト**設計が「小さい違い」には有効と確認
- [x] **大きい違い**の存在を体系的に整理（本ドキュメント）

### このフェーズではやらないこと（本実装の判断事項）

- [ ] 業種別・全社対応のホワイトリスト完成
- [ ] LLM／Agent Skill による動的解決の実装
- [ ] 業種別ナレッジの完全な体系化
- [ ] Arelle 等のXBRL標準ツールとの統合

これらは「最終成果物の設計」の問題であり、検証フェーズの完了基準ではない。

### 本実装着手時の最小スタート

1. **本ドキュメント（4.4 のナレッジ）** をベースに Agent Skill のプロンプトを設計
2. **TOPIX100 程度の規模**で動かしてみて、決定的部分と LLM 部分の比率を実測
3. キャッシュ機構を入れ、初回判定後はオフラインで動くようにする

---

## 6. 参考

- 本検証で実装したスクリプト: [step3a_lxml.py](step3a_lxml.py)
- XBRL データ構造の概観: [edinet_api_overview.md](edinet_api_overview.md) の「XBRL データ構造の要点」
- 検証結果: [verification_results.md](verification_results.md) の Step 3a
