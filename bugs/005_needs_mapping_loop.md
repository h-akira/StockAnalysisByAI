# BUG-005: mapping save 後も needs_mapping が再発する (ユーザーから見ると「同じものを 2 回書かされる」)

## ステータス

修正済み（検証待ち）

## 発見日

2026-05-23

## 概要

mapping を保存した直後の analyze で、最新期で取得成功した項目が古い期で取れない場合、再度 `needs_mapping` が返る。ユーザー視点では「マッピングが効いていない」と誤解し、もう一度マッピング作業を強いられる。

## 症状

manual_test history.md L2141-2152 で実観測:
1. analyze → needs_mapping (例: `SharesOutstanding` unresolved)
2. Claude が候補 payload を読み判定、mapping save
3. 再 analyze → **また** needs_mapping (同じ項目で)
4. 原因は古い年度 (2016-2018) の XBRL に該当要素が無いだけだが、ユーザーには不透明
5. やむなく mapping JSON の `unresolved[]` に追加して 3 回目の save、ようやく success

## 原因

[scripts/pipeline.py](../skills/japan-stock-analysis/scripts/pipeline.py) の `accepted_unresolved` は mapping JSON の `unresolved[]` を見るだけで、「mapping ありで一部期間だけ失敗」のケースを許容しない。

`timeseries.build_timeseries` が返す `unresolved_union` は全期 union で、「最新期は取れたが古い期で取れない項目」も union に含めて needs_mapping を再発させる。

## 影響範囲

- 影響銘柄: XBRL タクソノミが年度間で変化している銘柄すべて (古い期を遡るほど該当)
- 該当ファイル:
  - [scripts/pipeline.py](../skills/japan-stock-analysis/scripts/pipeline.py) `_analyze_one` の `accepted_unresolved` 計算
  - [scripts/timeseries.py](../skills/japan-stock-analysis/scripts/timeseries.py) `build_timeseries` の `unresolved_union` 集約

## 再現手順

1. 9531 をマッピングなしで analyze: `python3 ${CLAUDE_SKILL_DIR}/scripts/pipeline.py analyze --sec-code 9531`
2. needs_mapping で unresolved に `SharesOutstanding` 等が出る
3. mapping JSON で `SharesOutstanding` を最新期で取れる要素にマッピング、save
4. 再 analyze → 古い期で取れないため再度 needs_mapping

## 修正案

### 案1 (推奨): mapping に明示エントリのある項目は再エスカレーションしない

```python
mapped_keys = set(mapping_cached.get("mappings", {}).keys()) if mapping_cached else set()
unresolved = [
    u for u in unresolved
    if u not in accepted_unresolved and u not in mapped_keys
]
```

mapping に書いた時点で「Claude は判定済み」とみなす。期間別の取得失敗は BUG-006 の warning 改善で透明性を担保。後付け可能で破壊的でない。

### 案2: 期間別 unresolved の自動拡張

mapping save 時に「適用すると最新期で取れるが古い期で取れない」項目を自動検出して `unresolved[]` に追加。実装コスト高い。

## 対応

案1 (mapping に明示エントリのある項目は再エスカレーションしない) を採用。

変更:
- [skills/japan-stock-analysis/scripts/pipeline.py](../skills/japan-stock-analysis/scripts/pipeline.py) `_analyze_one`
  - `mapped_keys` (= `mapping_cached["mappings"]` のキー集合) を計算
  - `unresolved` フィルタ条件に `u not in mapped_keys` を追加
- [skills/japan-stock-analysis/tests/test_pipeline.py](../skills/japan-stock-analysis/tests/test_pipeline.py)
  - `test_analyze_does_not_reescalate_mapped_items` を追加 (mapping save 済の項目が一部期で取れなくても needs_mapping にならないことを assert)

期間別 NaN の可視性は BUG-006 の warning 改善で別途担保 (こちらは pending)。

## 関連

- 関連 bug: [BUG-006](006_per_period_nan_not_warned.md) (期間別 NaN の warning 欠落と同根)
- 観測ログ: `manual_test/history.md` L2141-2152
