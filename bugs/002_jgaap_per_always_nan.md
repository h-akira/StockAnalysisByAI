# BUG-002: JGAAP 銘柄で PER が全期 NaN (restated EPS が一切取れない)

## ステータス

未修正

## 発見日

2026-05-23

## 概要

`extract_restated_eps_from_zip` が IFRS 名前空間 (`BasicEarningsLossPerShareIFRSSummaryOfBusinessResults`) 一択で要素を探すため、JGAAP 銘柄では `restated_eps` が常に空辞書になり、PER が全期 NaN になる。

## 症状

- 9531 (東京瓦斯 JGAAP) を analyze すると `data_9531.json` の `metrics.PER` が全期 null
- `cache/split_adjust/9531.json` の `restated_eps` が `{}` (空辞書)
- warnings に「5 年窓外」と全 10 期が表示される (実態は restated EPS 自体が空)
- IFRS 銘柄 (7203, 6758) では正常に PER が出る

## 原因

[scripts/xbrl_extract.py](../skills/japan-stock-analysis/scripts/xbrl_extract.py) の `EPS_SUMMARY_ELEMENT` が `BasicEarningsLossPerShareIFRSSummaryOfBusinessResults` (IFRS suffix 付き) 一択。JGAAP の XBRL には IFRS suffix なしの `BasicEarningsLossPerShareSummaryOfBusinessResults` しか存在しないため、`get_fact` が常に `None` を返す。

P3.5 / P4 / Step 7 で IFRS 製造業 (Toyota, Sony) のみで検証してきたため、IFRS suffix なしの JGAAP variant の存在を考慮しなかった。

## 影響範囲

- 影響銘柄: **JGAAP を採用するすべての銘柄** (銀行・保険・電力・ガス・鉄道・建設など、非製造業の大半)
- 該当ファイル:
  - [scripts/xbrl_extract.py](../skills/japan-stock-analysis/scripts/xbrl_extract.py) `extract_restated_eps_from_zip`、`EPS_SUMMARY_ELEMENT`
  - [scripts/split_adjust.py](../skills/japan-stock-analysis/scripts/split_adjust.py) `resolve_split_adjust`
  - [scripts/pipeline.py](../skills/japan-stock-analysis/scripts/pipeline.py) warning 生成

## 再現手順

1. JGAAP 銘柄を analyze: `python3 ${CLAUDE_SKILL_DIR}/scripts/pipeline.py analyze --sec-code 9531`
2. `cache/split_adjust/9531.json` を開き `restated_eps` が `{}` であることを確認
3. `data_9531.json` の各 fiscal year の `metrics.PER` が null であることを確認

## 修正案

### 案1 (推奨): フォールバック順プローブ + audit field

[enhancements/002_jgaap_eps_summary_fallback.md](../enhancements/002_jgaap_eps_summary_fallback.md) 参照。

候補を優先順位で探索:
1. `BasicEarningsLossPerShareIFRSSummaryOfBusinessResults` (IFRS Basic)
2. `BasicEarningsLossPerShareSummaryOfBusinessResults` (JGAAP Basic)
3. `DilutedEarningsPerShareIFRSSummaryOfBusinessResults` (IFRS Diluted - 最後の手段)
4. `DilutedEarningsPerShareSummaryOfBusinessResults` (JGAAP Diluted - 最後の手段)

採用した候補を `eps_source` フィールドに記録して透明性確保。

### 案2: company_map.csv の `industry` で事前分岐

IFRS / JGAAP を事前判定して別ロジックに分岐。確実だが industry → 会計基準の対応表を別途持つ必要があり、保守コストが高い。案1 のフォールバック方式で十分。

## 対応

<!-- AI instruction: 修正完了後に追記するセクション。採用した修正案、または修正案にない独自対応の内容を記載する。変更したファイル・メソッドを列挙すること -->

## 関連

- 解決 enhancement: [ENH-002](../enhancements/002_jgaap_eps_summary_fallback.md)
- 関連 bug: [BUG-003](003_warning_message_misleading_for_jgaap.md) (warning メッセージ誤表示は同根)
- 参考: [README §D JGAAP 銀行業の Basic EPS](../skills/japan-stock-analysis/README.md)、[docs/p9_smoke_results.md](../skills/japan-stock-analysis/docs/p9_smoke_results.md)
- 検証環境: Skill commit `c8e0453` 付近、入力 9531/S100W10L、比較対象 7203/S100VWVY
