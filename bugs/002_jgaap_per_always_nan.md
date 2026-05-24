# BUG-002: JGAAP 銘柄で PER が全期 NaN (restated EPS が一切取れない)

## ステータス

修正済み（検証待ち）

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

ENH-002 案1 (4 候補フォールバック + audit field) を採用。BUG-003 (warning 改善) も同タイミングで対応済み。

変更:
- [skills/japan-stock-analysis/scripts/xbrl_extract.py](../skills/japan-stock-analysis/scripts/xbrl_extract.py)
  - 定数 `EPS_SUMMARY_ELEMENT` (単一文字列) を `EPS_SUMMARY_ELEMENTS` (4 候補 × audit tag のリスト) に置換
  - `extract_restated_eps_from_zip` の戻り値を `(offsets, sources)` の 2-tuple に変更し、各 offset で採用された変種タグ (ifrs_basic / jgaap_basic / ifrs_diluted / jgaap_diluted) を返すように
- [skills/japan-stock-analysis/scripts/split_adjust.py](../skills/japan-stock-analysis/scripts/split_adjust.py)
  - `SplitAdjustResult` に `eps_source: dict[str, str]` フィールドを追加 (period_end → tag)
  - cache JSON v1 に `eps_source` を追加 (後方互換 — 既存キャッシュは `cached.get("eps_source", {})` で空辞書フォールバック)
  - `_offset_tags_to_period_ends` ヘルパを追加
- [skills/japan-stock-analysis/scripts/metrics.py](../skills/japan-stock-analysis/scripts/metrics.py) `build_metrics`
  - 非 IFRS-Basic fallback が使われた場合に warning を発行 (ENH-002)
- [skills/japan-stock-analysis/tests/test_xbrl_extract.py](../skills/japan-stock-analysis/tests/test_xbrl_extract.py)
  - 新シグネチャに合わせて Sony/Toyota の restated_eps テストを更新、ifrs_basic タグも assert
- [skills/japan-stock-analysis/tests/test_split_adjust.py](../skills/japan-stock-analysis/tests/test_split_adjust.py)
  - 既存 `test_resolve_rebuilds_when_source_doc_id_changes` の mock 戻り値を 2-tuple に修正
  - `eps_source` が persist されることを assert
  - BUG-002 / BUG-003 / ENH-002 の warning 改善を別途検証する 2 テスト追加

JGAAP fixture (9531 等) は同梱せず実機 mock ベースで検証。実機で JGAAP 銘柄を analyze した際に PER が出ること・`eps_source` が `jgaap_basic` 等になることは別途確認推奨。

## 関連

- 解決 enhancement: [ENH-002](../enhancements/002_jgaap_eps_summary_fallback.md)
- 関連 bug: [BUG-003](003_warning_message_misleading_for_jgaap.md) (warning メッセージ誤表示は同根)
- 参考: [README §D JGAAP 銀行業の Basic EPS](../skills/japan-stock-analysis/README.md)、[docs/p9_smoke_results.md](../skills/japan-stock-analysis/docs/p9_smoke_results.md)
- 検証環境: Skill commit `c8e0453` 付近、入力 9531/S100W10L、比較対象 7203/S100VWVY
