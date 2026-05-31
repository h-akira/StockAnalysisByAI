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

### 案2: ENH-007 の AI 裁量レイヤで対処

[ENH-007](007_ai_driven_report_layer.md) の枠組みで、AI が PBR 異常を検出し `./scripts/{code}_pbr_split_adjust.py`
を生成して代替 JSON に補正 PBR を出す。会社固有の分割事情に柔軟だが、毎回 AI が判断するため一次計算の
監査性は案1 に劣る。**ENH-007 の最初の適用例**としては有効。

> 方針: PBR の分割補正は EPS と完全に対称な一般的処理なので、**案1（固定スクリプトで restated BPS を
> 実装）を根本対処とする**のが素直。ENH-007（案2）は「固定で拾いきれない会社固有の例外」を補う層で、
> PBR のような一般的補正はむしろ固定側に入れて土台を厚くすべき。両者は排他ではなく、案1 を本線、
> ENH-007 を例外対応の受け皿とする。

## 対応

<!-- AI instruction: 完了後に追記するセクション。採用した実現案、または独自対応の内容を記載する。変更したファイル・メソッドを列挙すること -->

## 関連

- レビュー: [manual_test_03/review_report.md](../manual_test_03/review_report.md) §3.1
- [split_adjust.py](../skills/japan-stock-analysis/scripts/split_adjust.py): restated EPS（本件の対称な先行実装）
- [ENH-007](007_ai_driven_report_layer.md): AI 裁量レポート層（例外対応の受け皿・案2）
- [SKILL.md](../skills/japan-stock-analysis/SKILL.md) §8: 「PBR は分割未補正」の既知制約（本件で解消を目指す）
