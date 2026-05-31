# BUG-009: financials.EarningsPerShare 系列に異なる基準の生 EPS が混在する

## ステータス

修正済み（検証待ち）

## 発見日

2026-05-31

## 概要

`data_*.json` / HTML レポートの `financials.EarningsPerShare`（財務本体に出力される生 EPS）が、年度間で抽出基準の異なる値を含んでおり、株式分割未補正と思われる古い期の値が混入して系列の連続性が損なわれている。PER 用の restated EPS（`split_adjust`）とは別レイヤの問題。

## 症状

- 東京ガス 9531 の `data_9531.json` で、各期の生 EPS と `ProfitLoss / SharesOutstanding` から逆算した implied EPS を比較すると、FY2019 以降は整合するが古い期はずれる。

| FY (期末) | ProfitLoss(十億) | Shares(百万) | implied EPS | reported EPS | 判定 |
|---|---|---|---|---|---|
| 2016-03 | 113.0 | (null) | — | 46.68 | ⚠️ 過小 |
| 2017-03 | 54.0 | (null) | — | 23.02 | ⚠️ 過小 |
| 2018-03 | 75.3 | (null) | — | 164.12 | ⚠️ 不整合 |
| 2019-03 | 84.3 | 451.4 | 186.80 | 187.60 | ✅ 整合 |
| 2020-03 | 43.6 | 442.4 | 98.47 | 98.07 | ✅ 整合 |
| 2021-03 | 50.5 | 442.4 | 114.08 | 112.26 | ✅ 整合 |
| 2022-03 | 90.3 | 441.0 | 204.71 | 201.84 | ✅ 整合 |
| 2023-03 | 281.5 | 434.9 | 647.36 | 646.99 | ✅ 整合 |
| 2024-03 | 170.1 | 400.5 | 424.88 | 411.88 | ✅ 整合 |
| 2025-03 | 72.7 | 388.9 | 186.86 | 192.22 | ✅ 整合 |

- FY2016=46.68 / FY2017=23.02 は、利益 1,130 億・540 億で株式数 ~4.4 億株なら本来 ~257 円・~123 円規模になるはずで一桁ずれている。当時の報告書の別概念（株式分割未補正の旧基準値、もしくは TextBlock 等から拾った非相当値）が混入している疑いが濃い。
- 古い期は SharesOutstanding が null（[BUG-006](006_per_period_nan_not_warned.md)）のため逆算検証ができず、見落とされやすい。

## 原因

- 生 EPS の抽出は `scripts/xbrl_extract.py` の Path B `BasicEarningsLossPerShareIFRSSummaryOfBusinessResults`（[xbrl_extract.py:80](../skills/japan-stock-analysis/scripts/xbrl_extract.py#L80)）および動的マッピング（東京ガスは JGAAP のため `mapping_resolver` 経由）で各 doc から取得される。
- PER 計算用の restated EPS は `scripts/split_adjust.py` が最新年報の遡及値から別系統で取得・補正するが、`financials.EarningsPerShare`（生 EPS）には**株式分割補正が一切かからない**。
- そのため、各年度の有報がそれぞれ報告した時点の基準（分割前/分割後）の EPS がそのまま系列に並び、年度間で基準が混在する。古い期ほど分割前基準の値が残りやすい。

## 影響範囲

- `scripts/xbrl_extract.py`: EarningsPerShare の Path B / 動的マッピング抽出
- `scripts/timeseries.py`: 年度系列の組み立て
- `scripts/json_export.py`: `financials.EarningsPerShare` の出力（[json_export.py:26](../skills/japan-stock-analysis/scripts/json_export.py#L26)）
- `scripts/html_report.py`: 生 EPS を描画する箇所（現状 EPS グラフが直接あるかは要確認）
- PER 計算自体は restated EPS（`split_adjust`）を使い、FY2020 以前は PER=NaN のため **PER 値そのものは汚染されていない**。問題は財務系列としての生 EPS のユーザー提示の信頼性。

## 再現手順

1. `cd skills/japan-stock-analysis`
2. 東京ガス 9531 を analyze（cache 済なら再 analyze）
3. `data_9531.json` の各 `fiscal_years[].financials.EarningsPerShare` と `ProfitLoss / SharesOutstanding` を突き合わせる
4. FY2016/2017/2018 が implied EPS と一桁〜大きくずれることを確認

## 調査（実施済み・2026-05-31）

manual_test_02 のキャッシュ（`manual_test_02/.claude/skills/japan-stock-analysis/cache/`）に
9531 の有報 XBRL 10 年分が残っていたため、各 doc の EPS 要素を直接ダンプして確認した。

**判明事項1: 抽出元は全期で統一されている（不一致ではない）**
全期の生 EPS は `jpcrp_cor:BasicEarningsLossPerShareSummaryOfBusinessResults` の
`CurrentYearDuration`（＝その有報の当期値）から取られている。要素・コンテキストの揺れではない。

**判明事項2: 真因は「各有報が報告した時点の基準値をそのまま並べている」こと**
東京ガスは株式分割を実施しており、後年の報告書ほど過去値が上方に再表示（遡及補正）される。
隣接有報の遡及列を突き合わせると基準のズレが明確:

| period | その期有報の当期値（=採用された生EPS） | 後年報告書での同期の遡及値 |
|---|---|---|
| 2016-03 | 46.68 | （5分割で約 5 倍に補正される世代） |
| 2017-03 | 23.02 | 翌 FY2018 報の Prior1 = **115.09**（約 5 倍） |
| 2018-03 | 164.12 | FY2019 報以降は 164.12 のまま（補正後世代に入る） |

FY2017 の当期値 23.02 と、翌年報告書での同期遡及値 115.09 の約 5 倍差が決定的証拠
（2017 年の株式分割による遡及補正）。古い期ほど分割補正前の小さい値が系列に残る。

**判明事項3: 補正後の統一系列は既に `split_adjust` が持っている**
`split_adjust.py` は最新年報の `Prior*YearDuration`（分割補正済み遡及 EPS）を抽出し
`cache/split_adjust/9531.json` にキャッシュ済み（FY2021〜2025 の 5 年分）。これが PER 計算に
使われる正しい統一基準の EPS。ただし最新報のカバレッジ（約 5 年）より古い期は範囲外で NaN。
（restated 値は分割だけでなく自己株買い等も反映するため生値と数 % 異なる期もある。例:
FY2024 生=411.88 / restated=401.09。）

> 結論: 抽出ロジックのバグではなく、「financials の生 EPS は報告時点基準のまま」という仕様上の
> 帰結。分割をまたぐ古い期で系列の連続性が崩れる。対処は「補正済み系列の活用」＋「補正できない
> 古い期の透明化」の組み合わせが妥当。

## 修正案（調査結果を踏まえ確定する暫定案）

### 案A: AI による整合確認と透明化（SKILL.md ガイド側）

[SKILL.md](../skills/japan-stock-analysis/SKILL.md) §7 に「生 EPS と `ProfitLoss / SharesOutstanding` の整合を確認し、一桁ずれ等の不整合期があればユーザーに明示する」旨を追記し、AI に検証を委ねる。コード変更なし。AI 介在思想に最も沿う。Shares が null の古い期は逆算できないため限界がある。

### 案B: timeseries でのコード整合チェックと warning 化

timeseries 構築時に、SharesOutstanding が取れる期について `ProfitLoss / Shares` と reported EPS の乖離を計算し、許容誤差（例 ±10%）超を warning 化する。決定的に検出できるが、Shares が null の FY2016/2017 は検出できない。

### 案C: 抽出元の一貫性確保（根本対処）

調査1・3 の結果、古い期が別基準の要素から来ていると判明した場合、SummaryOfBusinessResults の遡及列から統一的に取り直して基準を揃える。`scripts/xbrl_extract.py` の EarningsPerShare 抽出ロジックの修正を伴う。

> 方針は調査後に確定。透明化（案A or B）を先に入れて被害を可視化し、根本対処（案C）は出所確定後に判断するのが妥当と見込む。コード/AI どちらを主にするかは調査1の結果（抽出元が決定的か揺れているか）次第。

## 対応

「警告のみ追加（出力値・スキーマは変えない）」方針を採用。**会社差によるデグレを避けるため**、
コード警告と AI 指示の二層構成にした。

**コード側（保守的・会社差に強い条件のみ発火）** — `scripts/metrics.py`:
- `eps_consistency_warning(df)` を追加。`ProfitLoss / SharesOutstanding` から逆算した implied EPS と
  生 EPS の比が `_EPS_IMPLIED_GAP_RATIO`（3.0）以上ずれる期だけを warning 化する。
- 誤警報を出さないためのガード: SharesOutstanding が無い期はスキップ／`ProfitLoss<=0`・`EPS<=0` の
  赤字・ゼロ近傍はスキップ／3 倍未満の差（restatement ノイズ・希薄化・基準差）では発火しない。
  → restated EPS との比較は使わない（restated は自己株買い等で正常でも数 % ずれるため誤検知源）。
- `build_metrics` の warnings 先頭でこの検証を呼ぶ（yfinance/PER とは独立）。

**AI 側（コードで拾えない古い期をカバー）** — `SKILL.md` §7:
- 「生 EPS 系列の整合確認（BUG-009）」ブロックを追加。SharesOutstanding 欠落で逆算できない古い期は
  コードでは検出できないため、AI が生 EPS と ProfitLoss 水準を目視で照らし一桁ずれを指摘するよう指示。
  会社ごとに分割の有無・時期が異なるため「固定ルールで判定しきらず実値を見て判断」と明記。

**テスト** — `tests/test_metrics.py`:
- 桁ズレで発火（東京ガス FY2017 型）／正常な restatement ノイズで発火しない（トヨタ型）／赤字期スキップ／
  SharesOutstanding 欠落期スキップ、の 4 ケースを追加（デグレ回帰防止）。

出力 JSON のスキーマ・値は変更なし。`financials.EarningsPerShare` は引き続き報告時点基準の生値。

## 関連

- レビュー: [manual_test_02/review_report.md](../manual_test_02/review_report.md) §3.1
- [BUG-006](006_per_period_nan_not_warned.md): 古い期の SharesOutstanding が null で逆算検証できない件と表裏
- [ENH-002](../enhancements/002_jgaap_eps_summary_fallback.md): PER 用 restated EPS フォールバック（本件とは別レイヤ）
