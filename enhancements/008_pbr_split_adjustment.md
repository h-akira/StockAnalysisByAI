# ENH-008: PBR の株式分割補正（restated BPS による連続化）

## ステータス

未着手

## 起票日

2026-05-31

## 種別

改善

## 概要

PBR が株式分割をまたぐ期で歪む既知の制約（[SKILL.md](../skills/japan-stock-analysis/SKILL.md) §8）を是正する。restated EPS と同方式で、最新有報の `NetAssetsPerShareSummaryOfBusinessResults`（1 株当たり純資産＝BPS の遡及列）を用いて分割補正済み BPS 系列を取得し、PBR を連続比較可能にする。

## 背景・動機

manual_test_03（NTT 9432）で、2023 年の **1:25 分割**により PBR が 7 期中 5 期で 0.02〜0.07 倍という
壊滅的な異常値になった（[review_report.md](../manual_test_03/review_report.md) §3.1）:

| 期 | 株価(円) | BPS(円) | PBR | 株式数 |
|---|---:|---:|---:|---:|
| 2019-03 | 94.06 | 4,750.28 | 0.0198 | 1,950M |
| 2021-03 | 113.68 | 1,938.76 | 0.0586 | 3,901M |
| 2024-03 | 179.90 | 108.71 | 1.6548 | 90,550M |

**真因**: PBR = StockPrice / BPS、BPS = NetAssets / SharesOutstanding。株価は yfinance の**分割調整後**
だが、BPS は各年の**報告時点 SharesOutstanding（分割前）**で割るため、分子と分母の分割基準がずれる。
PER は restated EPS（[split_adjust.py](../skills/japan-stock-analysis/scripts/split_adjust.py)）で補正済み
なのに、**PBR/BPS だけ補正チャネルが無い**ため取り残されている。EPS で Step 7（pre-research）が解決した
分割問題が、BPS 側で未解決のまま残っている構図。

東京ガス（manual_test_02）の escalation payload に `NetAssetsPerShareSummaryOfBusinessResults` が
`CurrentYearInstant=4669.38` として実在することを確認済み。NTT の最新有報にも同様の遡及列があれば、
split_adjust と同じ「最新報告書の Prior*YearInstant を引く」方式で補正 BPS を得られる見込み。

## 要件

- 最新有報の `NetAssetsPerShareSummaryOfBusinessResults`（または相当要素）の
  `CurrentYearInstant` / `Prior*YearInstant` から、分割補正済みの BPS 遡及系列を取得する。
- PBR = StockPrice / restated_BPS で再計算し、分割をまたぐ期も連続比較可能にする。
- restated BPS がカバーしない古い期（最新報の遡及範囲外）は、restated EPS と同様に NaN ＋ warning とする。
- 補正 BPS が取れない銘柄（要素が無い等）は現行の生 BPS にフォールバックし、その旨を warning で明示する。
- EPS variant（ifrs/jgaap）同様、どの要素・コンテキストから取ったかを監査できるようにする。

## 影響範囲

- `scripts/split_adjust.py`: restated EPS と同様の restated BPS（または NetAssetsPerShare）抽出を追加。
  既存の `extract_restated_eps_from_zip` と対になる関数、キャッシュ（`cache/split_adjust/{code}.json`）への
  BPS 系列の追加。
- `scripts/xbrl_extract.py`: `NetAssetsPerShareSummaryOfBusinessResults` 系要素の抽出。
- `scripts/metrics.py`: `compute_metrics` の PBR 計算で restated BPS を優先使用（`compute_metrics` の
  `eps_for_per` と同型の `bps_for_pbr` 引数を追加する等）。
- `scripts/json_export.py` / `docs/json_schema.md`: BPS/PBR の出所メタの記載。
- warnings（PBR の補正可否・カバレッジ）。

## 実現案

### 案1: split_adjust に restated BPS を統合（固定スクリプト側の根本対処）

restated EPS の仕組みをそのまま BPS に横展開する。一次計算（固定スクリプト）の段階で PBR を補正済みに
する。監査可能で pytest 回帰も効く。EPS で実績のある方式の素直な拡張。**推奨**。

### 案2: ENH-007 の AI 裁量レイヤで対処 — 不採用

[ENH-007](007_ai_driven_report_layer.md) の枠組みで、AI が PBR 異常を検出し代替 JSON で補正 PBR を出す案。
会社固有の分割事情に柔軟だが、毎回 AI が判断するため一次計算の監査性・再現性が案1 に劣る。
**PBR 分割補正は EPS と対称な全銘柄共通の一般処理であり、AI 裁量に回すべき「例外」ではない**ため採らない。

> 方針: PBR の分割補正は EPS と完全に対称な一般的処理なので、**案1（固定スクリプトで restated BPS を実装）を
> 採用**する。ENH-007（AI 裁量レポート層）は「固定で一般化しづらい例外・雛形外要望」を扱う層であり、
> PBR のような一般補正は固定側（本 enhancement）に入れて土台を厚くするのが正しい住み分け。
> **ENH-007 の対象例ではない**（ENH-007 側でもそう統一済み）。

## 未確定事項（実装前に調査・確定する）

1. **IFRS 版 BPS 遡及要素の実在・正式名の調査**: 1 株当たり純資産の遡及列が実在することは
   **東京ガス（JGAAP）の escalation payload で `NetAssetsPerShareSummaryOfBusinessResults` を確認した**のみ。
   EPS では IFRS 版（`...IFRSSummaryOfBusinessResults`）と JGAAP 版が別要素だった前例があり
   （`xbrl_extract.py` の `EPS_SUMMARY_ELEMENTS`）、BPS も **IFRS 採用銘柄（例: NTT 9432）で要素名が異なる/
   存在しない可能性**がある。「EPS と完全対称」と断じる前に、IFRS・JGAAP 双方で実在要素名を実機確認し、
   要件の「（または相当要素）」を具体化する。取れない基準の銘柄は生 BPS フォールバック＋warning。
2. **5 年窓超の古い期は補正後も NaN になる制約の明示**: restated EPS と同様、最新有報の遡及列は通常
   過去 5 年分しかカバーしない。**NTT は 7 期中、補正できるのは最大 5 期で、最古の数期は補正 BPS が無く
   NaN になる**。「補正すれば全期連続化する」わけではない点を要件・warning に明記する
   （PER が 5 年窓外で NaN なのと同じ制約が PBR にも波及）。
3. **pytest fixture の追加**: 分割をまたぐ銘柄（理想は IFRS・JGAAP 各 1）の BPS 遡及列を含む fixture で、
   補正前後の PBR と窓外 NaN の挙動を回帰テストできるようにする。

## 対応

<!-- AI instruction: 完了後に追記するセクション。採用した実現案、または独自対応の内容を記載する。変更したファイル・メソッドを列挙すること -->

## 関連

- レビュー: [manual_test_03/review_report.md](../manual_test_03/review_report.md) §3.1
- [split_adjust.py](../skills/japan-stock-analysis/scripts/split_adjust.py): restated EPS（本件の対称な先行実装）
- [ENH-007](007_ai_driven_report_layer.md): AI 裁量レポート層。PBR 補正は本 enhancement（固定側）が担い、
  ENH-007 の対象ではない、と両ファイルで統一済み
- [SKILL.md](../skills/japan-stock-analysis/SKILL.md) §8: 「PBR は分割未補正」の既知制約（本件で解消を目指す）
